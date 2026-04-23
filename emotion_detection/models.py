from django.db import models
from django.contrib.auth.models import User
from typing import Dict, Optional, Set, List
from django.utils import timezone

# 定義七大情緒欄位
EMOTION_KEYS = [
    "happiness", "sadness", "anger", "surprise", "disgust", "fear", "neutral",
]

# 自動生成 au01 ~ au45 的欄位名稱列表
AU_FIELDS = [f"au{str(i).zfill(2)}" for i in range(1, 46)]

# --- [核心邏輯] AU 需求判斷與分數變化量 ---

def bucket(value: Optional[float]) -> str:
    """AU 強度分級: L(低), M(中), H(高)"""
    if value is None: return "0"
    if value < 0.2: return "L"
    if value < 0.5: return "M"
    return "H"

def analyze_au_scenarios(au_map: Dict[str, float], dominant_emotion: str = "neutral", emotions: Dict[str, float] = None) -> Set[str]:
    """
    [微表情需求判斷引擎 - 階層化情境版]
    
    依照情緒強度由高到低進行「分流判斷」：
    1. 正向基準 (>0.7)：只看開心特徵，忽略雜訊。
    2. 負面基準 (>0.7)：檢查嚴重阻礙，但在有笑時強制防呆。
    3. 平靜基準 (>0.5)：將皺眉/瞇眼解讀為「功能性需求」(如看不清楚)。
    4. 模糊地帶：執行一般性檢查。
    """
    normalized = {}
    for key, value in (au_map or {}).items():
        # 正規化鍵值
        clean = key.upper().replace("_R", "")
        if clean.startswith("AU"):
            normalized[clean[-4:]] = float(value)

    # 取得關鍵特徵數值
    val_au12 = normalized.get("AU12", 0.0) # 嘴角揚 (微笑)
    
    # 取得情緒分數 (預防 None)
    safe_emotions = emotions or {}
    happy_score = safe_emotions.get("happiness", 0.0)
    neutral_score = safe_emotions.get("neutral", 0.0)
    anger_score = safe_emotions.get("anger", 0.0)
    disgust_score = safe_emotions.get("disgust", 0.0)
    fear_score = safe_emotions.get("fear", 0.0)

    bk = {k: bucket(v) for k, v in normalized.items()}
    tags: Set[str] = set()
    
    def is_active(name: str) -> bool: return bk.get(name, "0") in ["M", "H"]

    # =========================================================
    # Level 1: 😊 正向情緒基準 (High Positive Confidence)
    # 條件：快樂分數 > 0.7 或 物理上有明顯微笑
    # 策略：只判斷正向 AU，忽略所有負面雜訊 (眼鏡/皺紋無效化)
    # =========================================================
    if happy_score > 0.7 or val_au12 > 0.35:
        
        # 1. 真誠滿意 (Eye + Lip Smile)
        if is_active("AU06") and is_active("AU12"):
            tags.add("真誠滿意")
        
        # 2. 尷尬/禮貌微笑 (Social Smile)
        # 雖然在笑，但帶有不自然的嘴角拉扯
        elif is_active("AU12") and is_active("AU14"):
            tags.add("尷尬微笑")
            
        # *在此模式下，直接返回，不進行後續負面檢查*
        return tags

    # =========================================================
    # Level 2: 😡 負面情緒基準 (High Negative Confidence)
    # 條件：生氣/厭惡/恐懼分數 > 0.7
    # 策略：判斷具體阻礙，但在「物理微笑」存在時強制防呆
    # =========================================================
    if anger_score > 0.7 or disgust_score > 0.7 or fear_score > 0.7:
        
        # [關鍵防呆] 微笑驗證
        # 如果嘴巴明明在笑 (AU12 > 0.4)，即使 PyFeat 說是厭惡，也視為誤判 (眼鏡/光影)
        # 直接返回空集合或視為平靜，不標記負面標籤
        if val_au12 > 0.4:
            return tags 

        # 3. 攻擊性憤怒 (Aggressive)
        # 皺眉 + 瞪眼
        if is_active("AU04") and is_active("AU05"):
            tags.add("攻擊性憤怒")
            
        # 4. 壓抑式盛怒 (Suppressed)
        # 皺眉 + 抿嘴/咬唇
        if is_active("AU04") and (is_active("AU23") or is_active("AU24")):
            tags.add("壓抑式盛怒")

        # 5. 生理反胃 (Repulsion)
        # 鼻皺 + 上唇提
        if is_active("AU09") and is_active("AU10"):
            tags.add("生理反胃")
        
        # 6. 強烈拒絕 (Rejection)
        # 上唇提 + 嘴角垂 + 下巴推
        if is_active("AU10") and is_active("AU15") and is_active("AU17"):
            tags.add("強烈拒絕")
            
        # 如果有標籤就返回，沒有則往下 (可能是假警報)
        if tags: return tags

    # =========================================================
    # Level 3: 😐 平靜基準 (High Neutral Confidence)
    # 條件：平靜分數 > 0.5
    # 策略：啟動「功能性/觀察型」解讀 (Look, Think, Listen)
    # 這解決了「平靜時皺眉被當成生氣」的問題
    # =========================================================
    if neutral_score > 0.5:
        
        # 7. 視力吃力 / 聚焦 (Focus / Visual)
        # 瞇眼 + 微皺眉 -> 看菜單/看螢幕
        if is_active("AU07") and is_active("AU04"):
            tags.add("視力吃力")
            
        # 8. 思考 / 猶豫 (Thinking)
        # 抿嘴/咬唇 -> 做決定 (在平靜下不需檢查 AU04 互斥，因為思考常皺眉)
        if is_active("AU23") or is_active("AU24"):
            tags.add("思考/猶豫")
            
        # 9. 沒聽清楚 (Auditory)
        # 皺眉 + 嘴微張 -> 蛤？
        if is_active("AU04") and is_active("AU25"):
            tags.add("沒聽清楚")
            
        # 10. 瀏覽 / 期待 (Browsing)
        # 抬眉 -> 尋找資訊
        if is_active("AU01") and is_active("AU02"):
            tags.add("瀏覽/期待")
            
        return tags

    # =========================================================
    # Level 4: 🌫️ 模糊地帶 (Ambiguous State)
    # 條件：上述皆未命中 (情緒混雜)
    # 策略：執行一般性阻礙檢查
    # =========================================================
    
    # 11. 困惑 / 聽不懂 (Confusion)
    # 內眉 + 皺眉
    if is_active("AU01") and is_active("AU04"):
        tags.add("困惑/聽不懂")
        
    # 12. 懷疑 / 價格敏感 (Skepticism)
    # 單邊嘴角 + 皺眉 (不信/懷疑)
    if is_active("AU14") and is_active("AU04"):
        tags.add("懷疑/價格敏感")

    return tags

def calculate_score_delta(emotions: dict, au_data: dict) -> float:
    """
    [分數變化量計算]
    """
    if not emotions: return 0.0
    
    # 取得主情緒 (views.py 已校正)
    dominant = max(emotions, key=emotions.get) if emotions else "neutral"
    
    # 1. 主情緒基本分
    base_delta = 0.0
    if dominant == "happiness": base_delta = 10.0
    elif dominant == "neutral": base_delta = 3.0    # 平靜穩定加分
    elif dominant == "surprise": base_delta = 5.0
    elif dominant == "sadness": base_delta = -8.0
    elif dominant == "fear": base_delta = -8.0
    elif dominant == "anger": base_delta = -12.0
    elif dominant == "disgust": base_delta = -10.0
    
    # 2. AU 微調 (傳入 emotions 以啟動情境感知)
    tags = analyze_au_scenarios(au_data, dominant, emotions)
    
    adjustments: List[float] = []

    # [正向/功能性 - 加分或微扣]
    if "真誠滿意" in tags: adjustments.append(5.0)
    if "瀏覽/期待" in tags: adjustments.append(2.0)
    if "思考/猶豫" in tags: adjustments.append(1.0)      # 鼓勵思考
    if "視力吃力" in tags: adjustments.append(-2.0)      # 微扣提醒
    if "沒聽清楚" in tags: adjustments.append(-4.0)      # 微扣提醒
    if "尷尬微笑" in tags: adjustments.append(2.0)      # 雖笑但尷尬

    # [一般阻礙 - 中扣分]
    if "困惑/聽不懂" in tags: adjustments.append(-4.0)
    if "懷疑/價格敏感" in tags: adjustments.append(-5.0)

    # [高強度危機 - 重扣分]
    if "強烈拒絕" in tags: adjustments.append(-8.0)
    if "壓抑式盛怒" in tags: adjustments.append(-8.0)
    if "攻擊性憤怒" in tags: adjustments.append(-10.0)
    if "生理反胃" in tags: adjustments.append(-10.0)

    # 取前2名加總
    adjustments.sort(key=abs, reverse=True)
    top_adjustments = adjustments[:2]
    sub_delta = sum(top_adjustments)

    total_delta = base_delta + sub_delta
    
    if total_delta > 20.0: total_delta = 20.0
    if total_delta < -20.0: total_delta = -20.0

    return round(total_delta, 2)


class CustomerEmotion(models.Model):
    """儲存每一幀 (Frame) 的偵測結果"""
    customer_id = models.CharField(max_length=100, default="unknown")
    employee = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    image_path = models.CharField(max_length=255)
    face_image = models.ImageField(upload_to="customer_faces/", null=True, blank=True)
    
    # 七大情緒機率
    happiness = models.FloatField(default=0.0)
    sadness = models.FloatField(default=0.0)
    anger = models.FloatField(default=0.0)
    surprise = models.FloatField(default=0.0)
    disgust = models.FloatField(default=0.0)
    fear = models.FloatField(default=0.0)
    neutral = models.FloatField(default=0.0)
    
    emotion_data = models.JSONField(default=dict, blank=True)
    
    # 累積總分
    score = models.FloatField(default=50.0)
    
    created_at = models.DateTimeField() 

    class Meta: ordering = ["-created_at"]
    def __str__(self): return f"{self.customer_id} @ {self.created_at}"

    @property
    def session_label(self): return self.customer_id
    @property
    def au_data(self): return {field: getattr(self, field, 0.0) for field in AU_FIELDS}
    @property
    def dominant_emotion(self):
        data = self.emotion_data or {}
        if not data: return "neutral"
        valid = {k: data.get(k, 0.0) for k in EMOTION_KEYS}
        if not valid: return "neutral"
        return max(valid, key=valid.get)

# 動態加入 AU 欄位
for field_name in AU_FIELDS:
    CustomerEmotion.add_to_class(field_name, models.FloatField(default=0.0))

class InterventionRecord(models.Model):
    session_label = models.CharField(max_length=100)
    analysis_date = models.DateField()
    average_score = models.FloatField(default=0.0)
    score = models.FloatField(default=0.0)
    emotion_label = models.CharField(max_length=20)
    au_signature = models.JSONField(default=dict) 
    frames = models.JSONField(default=list, blank=True)
    suggestions = models.JSONField(default=list, blank=True)
    source = models.CharField(max_length=20, default="auto")
    is_template = models.BooleanField(default=False)
    usage_count = models.PositiveIntegerField(default=0)
    needs_intervention = models.BooleanField(default=False)
    notes = models.CharField(max_length=20, default="")
    created_at = models.DateTimeField() 
    updated_at = models.DateTimeField(auto_now=True)
    class Meta: ordering = ["-analysis_date", "-updated_at"]
    def __str__(self): return f"{self.session_label} ({self.source})"