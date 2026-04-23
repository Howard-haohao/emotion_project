import base64
import logging
import os
import json
from datetime import datetime, time, timedelta

import cv2
import numpy as np
from PIL import Image
from django.conf import settings
from django.http import JsonResponse
from django.shortcuts import render, redirect
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.views import View
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET
from django_q.tasks import async_task
from feat import Detector
from django.contrib.auth import authenticate, login, logout, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.contrib.auth.forms import PasswordChangeForm

# [配置] 關閉煩人的 Log
logging.getLogger().setLevel(logging.ERROR)
logging.getLogger('django').setLevel(logging.ERROR)
from tqdm import tqdm
from functools import partialmethod
tqdm.__init__ = partialmethod(tqdm.__init__, disable=True)

from .marketing import (
    build_au_signature,
    generate_marketing_suggestion,
)

# 引入 models 中的邏輯
from .models import (
    CustomerEmotion, 
    InterventionRecord, 
    AU_FIELDS, 
    EMOTION_KEYS, 
    analyze_au_scenarios,
    calculate_score_delta
)

# --- 初始化 ---
logger = logging.getLogger(__name__)
detector = Detector(device="cpu")
FACE_CASCADE = cv2.CascadeClassifier(
    os.path.join(cv2.data.haarcascades, "haarcascade_frontalface_default.xml")
)

# --- 參數設定 ---
INTERVENTION_THRESHOLD = 40      # 紅線：平均分 < 40 介入
GREEN_LINE_THRESHOLD = 60        # 綠線：平均分 > 60 解除
AI_COOLDOWN_SECONDS = 5          # AI 發送冷卻時間
NEGATIVE_EMOTIONS = ['anger', 'sadness', 'disgust', 'fear']

# --- 輔助函式 ---

def _fallback_ai_feedback(dominant):
    sop = {
        "happiness": "顧客心情愉快，可主動推廣活動。",
        "sadness": "顧客情緒低落，請放慢語速關懷。",
        "anger": "顧客不滿，請安靜聆聽，不急解釋。",
        "surprise": "顧客感到驚訝，請把握機會介紹亮點。",
        "fear": "顧客有疑慮，請強調安全保障。",
        "disgust": "顧客反感，請觀察並移除干擾源。",
        "neutral": "情緒穩定，可多用開放式問句。",
    }
    return sop.get(dominant, sop["neutral"])

def _extract_au_data(faces):
    au_columns = [col for col in faces.columns if col.lower().startswith("au")]
    if not au_columns: return {}
    row = faces.iloc[0][au_columns]
    return {key: float(row[key]) for key in au_columns}

def _normalize_au_dict(raw):
    normalized = {}
    for key, value in (raw or {}).items():
        clean = key.lower().replace("_r", "")
        if clean.startswith("au"): normalized[clean[:4]] = float(value)
    return normalized

def _build_markers(points):
    """建立紅綠線標記點 (用於報表)"""
    markers = []
    below_active = False
    scores = [p["score"] for p in points]
    times = [p["time"] for p in points]
    
    for i in range(len(scores)):
        current_s = scores[i]
        t = times[i]
        if current_s < INTERVENTION_THRESHOLD and not below_active:
            markers.append({"time": t, "type": "low"})
            below_active = True
        elif current_s >= GREEN_LINE_THRESHOLD and below_active:
            markers.append({"time": t, "type": "recover"})
            below_active = False
    return markers

def _evaluate_interventions(sessions, records_by_session, analysis_date):
    """分析 AI 介入成效與達成率"""
    interventions_report = []
    ai_records = InterventionRecord.objects.filter(
        analysis_date=analysis_date, source__in=['ai', 'cached']
    ).order_by('created_at')

    total_red = len(ai_records)
    success_green = 0

    for intervention in ai_records:
        cid = intervention.session_label
        trig = intervention.created_at
        recs = records_by_session.get(cid, [])
        if not recs: 
            recs = list(CustomerEmotion.objects.filter(customer_id=cid, created_at__date=analysis_date))

        score_before = intervention.score 
        end = trig + timedelta(seconds=180) 
        after = [r for r in recs if trig < r.created_at <= end]

        res = "⏳ 觀察中"
        score_after = score_before

        if after:
            scores = [r.score for r in after]
            if any(s >= GREEN_LINE_THRESHOLD for s in scores):
                res = "✅ 達成綠線"
                success_green += 1
                score_after = max(scores)
            else:
                score_after = scores[-1]
                if score_after > score_before + 10: res = "📈 有效提升"
                else: res = "❌ 未達標"
        else:
            res = "❓ 資料不足"

        adv = ""
        if intervention.suggestions:
            f = intervention.suggestions[0]
            adv = f.get('advice', '') if isinstance(f, dict) else str(f)
            
        emp = "Unknown"
        if recs and recs[0].employee: emp = recs[0].employee.username

        local_trig = timezone.localtime(trig)

        interventions_report.append({
            "time": local_trig.strftime("%H:%M:%S"), 
            "customer_id": cid, 
            "employee": emp,
            "advice": adv, 
            "score_before": round(score_before, 1), 
            "score_after": round(score_after, 1), 
            "result": res
        })
    
    rate = round((success_green/total_red)*100, 1) if total_red > 0 else 0.0
    return interventions_report, rate

def should_trigger_ai_smart(customer_id):
    """AI 發送頻率控制"""
    last = InterventionRecord.objects.filter(session_label=customer_id, source__in=['ai', 'cached']).order_by("-created_at").first()
    if not last: return True 
    
    diff = (timezone.now() - last.created_at).total_seconds()
    if diff < AI_COOLDOWN_SECONDS: return False 
    
    return True

# --- [核心] 平衡版情緒校正邏輯 (Trust High Confidence) ---
def _correct_emotion_logic(dominant, emotions, norm_au):
    """
    修正 PyFeat 的常見誤判。
    1. 微笑優先：有笑就判開心。
    2. 信心優先：如果模型對某情緒信心 > 0.5，直接採納，不進行嚴格 AU 過濾。
    3. 低信心過濾：如果信心低，才執行嚴格 AU 檢查。
    """
    happy_score = emotions.get("happiness", 0.0)
    dom_score = emotions.get(dominant, 0.0) # 主情緒的信心分數
    
    val_au04 = norm_au.get("AU04", 0.0) # 皺眉
    val_au09 = norm_au.get("AU09", 0.0) # 鼻皺
    val_au10 = norm_au.get("AU10", 0.0) # 上唇提
    val_au12 = norm_au.get("AU12", 0.0) # 嘴角揚
    val_au01 = norm_au.get("AU01", 0.0) # 內眉
    val_au15 = norm_au.get("AU15", 0.0) # 嘴角垂
    val_au20 = norm_au.get("AU20", 0.0) # 嘴角拉扯

    # 1. 微笑優先 (最高原則)
    if happy_score > 0.25 or val_au12 > 0.35:
        return "happiness"

    # 2. 信心優先 (Trust Model)
    if dom_score > 0.5:
        return dominant

    # --- 以下只針對「信心不足 (<0.5)」的模糊地帶進行嚴格檢查 ---
    
    thresh = 0.4 # 低信心時的嚴格門檻

    # 3. 厭惡驗證 (防眼鏡誤判)
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

    # 6. 驚訝/恐懼驗證
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

# --- Views (Auth & Management) ---

def login_view(request):
    if request.method == 'POST':
        u = request.POST.get('username'); p = request.POST.get('password')
        user = authenticate(request, username=u, password=p)
        if user:
            login(request, user)
            return redirect('index')
        else: return render(request, 'login.html', {'error': '帳號或密碼錯誤'})
    return render(request, 'login.html')

def logout_view(request):
    logout(request)
    return redirect('login')

@login_required(login_url='/login/')
def manage_employees(request):
    if not request.user.is_superuser: return redirect('index')
    users = User.objects.exclude(id=request.user.id).order_by('date_joined')
    return render(request, "manage_employees.html", {"users": users})

@login_required(login_url='/login/')
def add_employee(request):
    if not request.user.is_superuser: return JsonResponse({'status':'error'}, status=403)
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            User.objects.create_user(username=data['username'], password=data['password'], email=data.get('email',''))
            return JsonResponse({'status':'ok'})
        except Exception as e: return JsonResponse({'status':'error', 'message':str(e)})
    return JsonResponse({'status':'error'})

@login_required(login_url='/login/')
def delete_employee(request, user_id):
    if not request.user.is_superuser: return JsonResponse({'error':'Forbidden'}, status=403)
    if request.method == "POST":
        User.objects.filter(id=user_id).delete()
        return JsonResponse({'status':'ok'})
    return JsonResponse({'status':'error'})

@login_required(login_url='/login/')
def profile_view(request):
    user = request.user; msg = ""
    if request.method == 'POST':
        user.email = request.POST.get('email', user.email)
        user.save()
        form = PasswordChangeForm(user, request.POST)
        if form.is_valid():
            user = form.save(); update_session_auth_hash(request, user); msg = "更新成功"
        elif not request.POST.get('old_password'): msg = "信箱已更新"
        else: msg = "密碼錯誤"
    else: form = PasswordChangeForm(user)
    return render(request, "profile.html", {"form": form, "user": user, "success_msg": msg})

# --- Views (Pages) ---

@login_required(login_url='/login/')
def index(request): return render(request, "index.html")

@login_required(login_url='/login/')
def report_view(request): return render(request, "report.html")

# --- Views (API) ---

def get_new_session_id(request):
    if not request.user.is_authenticated: return JsonResponse({'error': 'Unauthorized'}, status=401)
    
    now = timezone.localtime(timezone.now())
    date_str = now.strftime("%Y%m%d") 
    prefix = f"{date_str}c"
    
    existing = CustomerEmotion.objects.filter(customer_id__startswith=prefix).values_list('customer_id', flat=True).distinct()
    max_seq = 0
    for cid in existing:
        try:
            seq = int(cid.replace(prefix, ""))
            if seq > max_seq: max_seq = seq
        except: continue
    return JsonResponse({"session_id": f"{prefix}{max_seq + 1}"})

@csrf_exempt
def detect_emotion(request):
    """
    核心偵測函式 (含平均分與連續情緒判斷 + 狀態保持)
    """
    if request.method != "POST": return JsonResponse({"error": "Invalid"}, status=400)
    image_data = request.POST.get("image")
    customer_id = request.POST.get("customer_id")
    if not customer_id or not image_data: return JsonResponse({"error": "No Data"}, status=400)

    try:
        # 1. 影像前處理
        header, imgstr = image_data.split(";base64,")
        nparr = np.frombuffer(base64.b64decode(imgstr), np.uint8)
        img_bgr = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        
        if img_bgr.shape[1] > 640:
            scale = 640/img_bgr.shape[1]
            img_bgr = cv2.resize(img_bgr, (0,0), fx=scale, fy=scale)
        
        gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
        rects = FACE_CASCADE.detectMultiScale(gray, 1.1, 5, minSize=(60, 60))
        
        # [狀態保持] 沒偵測到人臉時，嘗試回傳上一筆狀態，避免分數歸零
        if len(rects) == 0: 
            prev = CustomerEmotion.objects.filter(customer_id=customer_id).order_by("-created_at").first()
            if prev:
                last_adv = InterventionRecord.objects.filter(session_label=customer_id).order_by("-created_at").first()
                adv_text = ""
                if last_adv and last_adv.suggestions:
                    adv_text = last_adv.suggestions[0].get("advice", "")
                elif not last_adv:
                    adv_text = "(暫時無法偵測人臉)"

                return JsonResponse({
                    "dominant_emotion": prev.dominant_emotion,
                    "intervention_score": prev.score,
                    "marketing_text": adv_text,
                    "customer_id": customer_id,
                    "status": "no_face_kept"
                })
            return JsonResponse({"dominant_emotion": "neutral", "status": "no_face"})
        
        x, y, w, h = max(rects, key=lambda r: r[2]*r[3])
        H, W = img_bgr.shape[:2]
        pad = int(w*0.1)
        face = img_bgr[max(0,y-pad):min(H,y+h+pad), max(0,x-pad):min(W,x+w+pad)]
        
        ts = timezone.localtime(timezone.now()).strftime("%Y%m%d%H%M%S%f")
        fname = f"{customer_id}_{ts}.jpg"
        path = os.path.join(settings.MEDIA_ROOT, "customer_faces", fname)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        cv2.imwrite(path, face)
        
        # 2. PyFeat 偵測
        try:
            faces = detector.detect_image(path)
        except:
            return JsonResponse({"dominant_emotion": "neutral", "status": "feat_error"})

        if faces.empty: return JsonResponse({"dominant_emotion": "neutral", "status": "feat_fail"})

        # 3. 數據提取
        emos = faces.iloc[0][EMOTION_KEYS].to_dict()
        au_raw = _extract_au_data(faces)
        norm_au = _normalize_au_dict(au_raw)
        
        raw_dom = max(emos, key=emos.get)
        
        # 3.1 情緒校正
        dom = _correct_emotion_logic(raw_dom, emos, norm_au)
        
        # 4. 累積計分 (單次)
        prev_record = CustomerEmotion.objects.filter(customer_id=customer_id).order_by("-created_at").first()
        current_base_score = prev_record.score if prev_record else 50.0
        
        calc_emos = emos.copy()
        if dom == "happiness": calc_emos["happiness"] = 1.0
        elif dom == "neutral": calc_emos["neutral"] = 1.0
        
        delta = calculate_score_delta(calc_emos, norm_au)
        new_score = current_base_score + delta
        new_score = max(0.0, min(100.0, new_score))
        
        # [關鍵] 傳入 emotions (raw dict) 以支援 models.py 的高強度判斷
        tags = analyze_au_scenarios(norm_au, dom, emos)

        # 5. 寫入 DB
        now_tw = timezone.localtime(timezone.now())
        current_obj = CustomerEmotion.objects.create(
            customer_id=customer_id, 
            face_image=f"customer_faces/{fname}", 
            image_path=f"customer_faces/{fname}",
            emotion_data=emos, 
            employee=request.user if request.user.is_authenticated else None,
            score=new_score,
            created_at=now_tw,
            **emos, **norm_au 
        )

        # 6. 計算最近 3 次的統計數據 (Average & Consecutive)
        recent_3 = CustomerEmotion.objects.filter(customer_id=customer_id).order_by("-created_at")[:3]
        
        avg_score = new_score 
        is_consecutive_same = False
        
        if len(recent_3) == 3:
            total_s = sum(r.score for r in recent_3)
            avg_score = total_s / 3.0
            
            emotions_list = []
            for r in recent_3:
                r_norm_au = _normalize_au_dict(r.au_data)
                r_dom = _correct_emotion_logic(r.dominant_emotion, r.emotion_data, r_norm_au)
                emotions_list.append(r_dom)
            
            if emotions_list[0] == emotions_list[1] == emotions_list[2]:
                is_consecutive_same = True

        # 7. 定義觸發條件 (紅線)
        # 條件 A: 平均分 < 40
        is_low_avg = avg_score < INTERVENTION_THRESHOLD
        
        # 條件 B: 連續 3 次相同情緒 (包含平靜、開心、生氣)
        # [關鍵修正] 不再排除 neutral，只要停滯就觸發
        is_stuck = is_consecutive_same
        
        should_trigger = is_low_avg or is_stuck
        
        # 綠線條件: 平均分 > 60
        is_green = avg_score > GREEN_LINE_THRESHOLD
        
        m_status = "none"

        # 如果符合觸發條件，且冷卻時間已過 -> 呼叫 AI
        if should_trigger:
            if should_trigger_ai_smart(customer_id):
                async_task('emotion_detection.marketing.generate_marketing_suggestion', customer_id)
                m_status = "processing"
        
        # 準備前端顯示 (最近 4 筆軌跡)
        recent_4 = CustomerEmotion.objects.filter(customer_id=customer_id).order_by("-created_at")[:4]
        hist = []
        for r in reversed(recent_4):
            r_norm_au = _normalize_au_dict(r.au_data)
            r_dom = _correct_emotion_logic(r.dominant_emotion, r.emotion_data, r_norm_au)
            hist.append({"emotion": r_dom, "score": r.score})

        last_rec = InterventionRecord.objects.filter(session_label=customer_id).order_by("-created_at").first()
        txt, src = "", ""
        if last_rec:
            src = last_rec.source
            if last_rec.suggestions:
                txt = last_rec.suggestions[0].get("advice") if isinstance(last_rec.suggestions[0], dict) else str(last_rec.suggestions[0])
        
        if not txt: txt = _fallback_ai_feedback(dom)

        return JsonResponse({
            "dominant_emotion": dom, 
            "intervention_score": round(new_score, 1), 
            "recent_history": hist,
            "scenario_tags": sorted(tags), 
            "is_red_zone": is_low_avg, 
            "is_green_zone": is_green, 
            "marketing_status": m_status,
            "marketing_text": txt, 
            "marketing_source": src, 
            "customer_id": customer_id,
            "face_box": {"x":int(x),"y":int(y),"w":int(w),"h":int(h)}
        })
    except Exception as e:
        logger.error(f"Error: {e}")
        return JsonResponse({"error": str(e)}, status=500)

@require_GET
def marketing_status(request):
    rec = InterventionRecord.objects.filter(session_label=request.GET.get("record_id")).order_by("-created_at").first()
    if not rec: return JsonResponse({"status": "pending"})
    txt = ""
    if rec.suggestions: txt = rec.suggestions[0].get("advice")
    return JsonResponse({"status": "done" if rec.notes=="done" else "pending", "marketing_text": txt, "marketing_source": rec.source})

@require_GET
def report_data(request):
    if not request.user.is_authenticated: return JsonResponse({'error': 'Unauthorized'}, status=401)
    d_str = request.GET.get("date")
    if not d_str: return JsonResponse({"status": "error"})
    
    start = timezone.make_aware(datetime.combine(parse_date(d_str), time.min))
    end = timezone.make_aware(datetime.combine(parse_date(d_str), time.max))
    
    base = CustomerEmotion.objects.filter(created_at__range=(start, end))
    if not request.user.is_superuser: base = base.filter(employee=request.user)
    recs = base.order_by("customer_id", "created_at")
    
    if not recs.exists(): return JsonResponse({"status": "no_data"})

    sess = {}; by_sess = {}; totals = []
    for r in recs:
        s = r.score
        emp = r.employee.username if r.employee else "Unknown"
        ss = sess.setdefault(r.customer_id, {"customer_id": r.customer_id, "employee": emp, "points": [], "avg_score": 0})
        
        local_time = timezone.localtime(r.created_at).strftime("%H:%M:%S")
        ss["points"].append({"time": local_time, "score": s})
        by_sess.setdefault(r.customer_id, []).append(r)
        totals.append(s)

    for s in sess.values(): 
        if s["points"]: s["avg_score"] = round(sum(p["score"] for p in s["points"])/len(s["points"]), 2)
        s["markers"] = _build_markers(s["points"])
    
    inter, rate = _evaluate_interventions(sess, by_sess, parse_date(d_str))
    
    return JsonResponse({
        "status": "ok", "sessions": list(sess.values()),
        "daily_avg": round(sum(totals)/len(totals), 2) if totals else 0,
        "interventions": inter, "success_rate": rate
    })

class EmotionDetectionView(View):
    def get(self, request): return JsonResponse({"msg": "OK"})

class EmotionHistoryView(View):
    def get(self, request): return JsonResponse({"msg": "OK"})