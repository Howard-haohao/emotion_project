import logging
import os
from typing import Dict, Optional, Set, Tuple, List
from datetime import timedelta

from django.conf import settings
from django.utils import timezone
from openai import OpenAI

# 引入共用的 AU 分析邏輯與常數
from .models import (
    AU_FIELDS, 
    CustomerEmotion, 
    InterventionRecord, 
    analyze_au_scenarios,
    EMOTION_KEYS # 確保能讀取情緒鍵值
)

logger = logging.getLogger(__name__)

# --- 設定與參數 ---
AI_RESPONSE_CHAR_LIMIT = 60 
OPENAI_MODEL = getattr(settings, "OPENAI_MODEL", "gpt-4o-mini")

# SOP 備案建議
DEFAULT_SOP_SUGGESTIONS = {
    "happiness": "顧客反應正向，可嘗試建立連結或推廣會員。",
    "sadness": "顧客似乎有些困擾，請放慢語速，主動關懷。",
    "anger": "察覺顧客不滿，請安靜聆聽，避免反駁。",
    "surprise": "顧客對資訊感到驚訝，請把握機會介紹亮點。",
    "fear": "顧客可能對價格或條款有疑慮，請強調保障。",
    "disgust": "顧客感到不適或懷疑，請確認需求並提供替代方案。",
    "neutral": "顧客正在思考或瀏覽，可適時提供熱銷推薦。",
}

_ai_client: Optional[OpenAI] = None

def _get_openai_client() -> Optional[OpenAI]:
    """取得 OpenAI Client 單例"""
    global _ai_client
    if _ai_client is not None:
        return _ai_client

    api_key = getattr(settings, "OPENAI_API_KEY", None) or os.getenv("OPENAI_API_KEY")
    if not api_key:
        logger.warning("OPENAI_API_KEY 未設定，將使用 SOP 預設建議。")
        return None

    _ai_client = OpenAI(api_key=api_key)
    return _ai_client

# --- 輔助函式 ---

def build_au_signature(emotion_label: str, tags: Set[str]) -> str:
    """建立語意簽章 (Cache Key)"""
    tag_part = "NONE" if not tags else ",".join(sorted(tags))
    return f"{(emotion_label or 'neutral').lower()}|{tag_part}"

def _fallback_advice(emotion_label: Optional[str]) -> str:
    label = (emotion_label or "neutral").lower()
    return DEFAULT_SOP_SUGGESTIONS.get(label, DEFAULT_SOP_SUGGESTIONS["neutral"])

def _normalize_au_data(au_data: Dict[str, float]) -> Dict[str, float]:
    """將輸入的 AU 資料正規化為 AU01, AU02... 格式"""
    normalized = {}
    for field in AU_FIELDS:
        value = (au_data or {}).get(field) if isinstance(au_data, dict) else None
        normalized[field.upper()] = float(value) if value is not None else 0.0
    return normalized

# --- [關鍵] 階層化情緒校正邏輯 (必須與 views.py 保持完全一致) ---
def _correct_emotion_logic(dominant, emotions, norm_au):
    """
    [行銷模組專用] 
    在生成歷史軌跡時，必須重新校正情緒，確保 AI 看到的是「過濾後」的真實狀態。
    """
    if not emotions: return "neutral"
    
    happy_score = emotions.get("happiness", 0.0)
    dom_score = emotions.get(dominant, 0.0) # 主情緒的信心分數
    
    # AU 特徵
    val_au04 = norm_au.get("AU04", 0.0) # 皺眉
    val_au09 = norm_au.get("AU09", 0.0) # 鼻皺
    val_au10 = norm_au.get("AU10", 0.0) # 上唇提
    val_au12 = norm_au.get("AU12", 0.0) # 嘴角揚
    val_au01 = norm_au.get("AU01", 0.0) # 內眉
    val_au15 = norm_au.get("AU15", 0.0) # 嘴角垂
    val_au20 = norm_au.get("AU20", 0.0) # 嘴角拉扯

    # 1. 微笑優先 (Smile Protection)
    if happy_score > 0.25 or val_au12 > 0.35:
        return "happiness"

    # 2. 信心優先 (Trust Model > 0.5)
    # 與 views.py 同步：如果模型有過半把握，就採納，不進行嚴格 AU 檢查
    if dom_score > 0.5:
        return dominant

    # --- 以下針對低信心 (<0.5) 進行嚴格檢查 ---
    thresh = 0.4

    # 3. 厭惡驗證 (加權互補)
    if dominant == "disgust":
        weighted_disgust = (val_au09 * 0.7) + (val_au10 * 1.3)
        if weighted_disgust < thresh:
            return "neutral"

    # 4. 生氣驗證
    if dominant == "anger":
        if val_au04 < 0.3:
            return "neutral"

    # 5. 悲傷驗證
    if dominant == "sadness":
        if val_au01 < 0.15 and val_au15 < 0.15:
            return "neutral"

    # 6. 驚訝/恐懼 驗證
    if dominant == "surprise":
        if (norm_au.get("AU01",0) + norm_au.get("AU02",0)) < 0.1:
            return "neutral"
    
    if dominant == "fear":
        if val_au20 < 0.2 and val_au04 < 0.25:
            return "neutral"

    # 7. 平靜中的隱藏快樂
    if dominant == "neutral":
        if happy_score > 0.35:
            return "happiness"
            
    return dominant

def find_cached_suggestion(semantic_signature):
    """快取檢查 (最近 7 天)"""
    cutoff = timezone.now() - timedelta(days=7)
    return (
        InterventionRecord.objects.filter(
            au_signature=semantic_signature,
            source="ai",
            created_at__gte=cutoff
        )
        .order_by("-created_at")
        .first()
    )

# --- AI 生成邏輯 ---

def generate_ai_suggestion(
    history_summary: List[str],
    current_emotion: str,
    current_score: float,
    current_tags: Set[str]
) -> Tuple[str, list, str]:
    """呼叫 OpenAI 生成建議"""
    fallback = _fallback_advice(current_emotion)
    client = _get_openai_client()
    
    if client is None:
        return fallback, [], "sop"

    history_text = "\n".join(history_summary)
    tags_text = ", ".join(current_tags) if current_tags else "無明顯特徵"

    # [關鍵 Prompt 更新] 自由發揮 + 商業安全守則 + 需求導向解讀
    prompt = (
        f"你是資深的服務行為心理學家。請根據顧客連續的情緒軌跡，判斷情境並給予店員行動建議。\n\n"
        f"【情緒軌跡 (舊 -> 新)】\n{history_text}\n\n"
        f"【當前狀態】\n"
        f"- 修正後主情緒：{current_emotion}\n"
        f"- 滿意度：{current_score:.1f} (基準50)\n"
        f"- 需求訊號：{tags_text}\n\n"
        f"【訊號參考 (需求導向)】\n"
        f"- 「視力吃力」：瞇眼+微皺眉 → 非生氣，是看不清楚菜單/螢幕。\n"
        f"- 「思考/猶豫」：抿嘴+無皺眉 → 正向投入，正在做決定，請給予空間或推薦。\n"
        f"- 「沒聽清楚」：皺眉+嘴開 → 請建議放慢語速或重述。\n"
        f"- 「懷疑/價格敏感」：單邊嘴角/下巴緊 → 對價格或價值有疑慮。\n"
        f"- 「真誠滿意」：眼角笑+嘴角笑 → 應給予肯定並保持。\n\n"
        f"【建議守則 (Guardrails)】\n"
        f"1. 🚫 **嚴禁** 建議給予折扣、降價、優惠券或承諾贈品 (你沒有權限)。\n"
        f"2. ✅ 請專注於：溝通技巧、服務動作 (遞水、拿菜單)、同理心安撫、產品價值強調。\n"
        f"3. 請分析變化趨勢 (例如：從困惑轉為思考)，語氣自然專業，像老練店長提醒。\n"
        f"4. 50字以內。"
    )

    try:
        response = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": "你是一個觀察入微的行為心理學家與銷售專家。"},
                {"role": "user", "content": prompt}
            ],
            max_tokens=150,
            temperature=0.8, # 保持靈活性
        )
        text_response = response.choices[0].message.content.strip()
        clean = text_response.replace("建議：", "").replace("店長提醒：", "").replace("分析：", "")
        
        return clean[:AI_RESPONSE_CHAR_LIMIT], [], "ai"

    except Exception as e:
        logger.error(f"[OpenAI Failed] {str(e)}")
        return f"(連線忙碌) {fallback}", [], "sop"


def generate_marketing_suggestion(target_ref, *args, **kwargs):
    """
    Task Entry Point
    """
    try:
        if isinstance(target_ref, int):
            current_obj = CustomerEmotion.objects.get(id=target_ref)
        else:
            current_obj = CustomerEmotion.objects.filter(customer_id=str(target_ref)).order_by("-created_at").first()
            
        if not current_obj:
            logger.warning(f"Task failed: CustomerEmotion {target_ref} not found")
            return

    except Exception as e:
        logger.error(f"Error fetching CustomerEmotion: {e}")
        return

    # 1. 數據正規化
    norm_au = _normalize_au_data(current_obj.au_data)
    
    # 2. [關鍵] 執行情緒校正
    # 確保行銷模組使用的是「過濾後」的正確情緒
    raw_dom = current_obj.dominant_emotion 
    corrected_dom = _correct_emotion_logic(raw_dom, current_obj.emotion_data, norm_au)
    
    # 3. 分析特徵 (傳入 emotions 以支援高強度判斷)
    tags = analyze_au_scenarios(norm_au, corrected_dom, current_obj.emotion_data)
    
    # 建立簽章
    sig = build_au_signature(corrected_dom, tags)
    sorted_tags = sorted(tags)

    # 4. 快取檢查
    cached_record = find_cached_suggestion(sig)
    advice = ""
    source = ""

    if cached_record and cached_record.suggestions:
        first = cached_record.suggestions[0]
        advice = first.get("advice") if isinstance(first, dict) else str(first)
        source = "cached"
        logger.info(f"Cache Hit for {sig}: {advice}")
    else:
        # 5. 準備歷史資料 (Trends) - 重建歷史真相
        recent_records = CustomerEmotion.objects.filter(
            customer_id=current_obj.customer_id,
            created_at__lte=current_obj.created_at # 取當下之前的紀錄
        ).order_by("-created_at")[:3]
        
        history_records = list(reversed(recent_records))
        history_summary = []
        
        for i, rec in enumerate(history_records):
            # 對每一筆歷史資料也都要做正規化與校正
            h_norm_au = _normalize_au_data(rec.au_data)
            h_raw_dom = rec.dominant_emotion
            h_corrected_dom = _correct_emotion_logic(h_raw_dom, rec.emotion_data, h_norm_au)
            
            # 使用校正後的情緒去分析當時的 tags (需傳入 emotion_data)
            r_tags = analyze_au_scenarios(h_norm_au, h_corrected_dom, rec.emotion_data)
            tag_str = ",".join(r_tags) if r_tags else "無明顯特徵"
            
            time_label = f"T-{len(history_records)-i}"
            history_summary.append(
                f"{time_label}: {h_corrected_dom} (特徵: {tag_str})"
            )

        # 6. 呼叫 AI (傳入校正後的資訊)
        advice, _, source = generate_ai_suggestion(
            history_summary=history_summary,
            current_emotion=corrected_dom,
            current_score=current_obj.score,
            current_tags=tags
        )

    # 7. 寫入 InterventionRecord
    InterventionRecord.objects.create(
        session_label=current_obj.session_label,
        analysis_date=timezone.localtime(current_obj.created_at).date(),
        emotion_label=corrected_dom, # 存入校正後的情緒
        au_signature=sig,
        average_score=current_obj.score,
        score=current_obj.score,
        suggestions=[{"emotion": corrected_dom, "advice": advice, "tags": sorted_tags}],
        frames=[{
            "image_path": current_obj.image_path,
            "captured_at": str(current_obj.created_at),
            "emotion_data": current_obj.emotion_data,
            "au_data": current_obj.au_data,
        }],
        source=source,
        notes="done",
        created_at=timezone.localtime(timezone.now())
    )
    
    if source == "ai":
        logger.info(f"AI Generated: {advice}")