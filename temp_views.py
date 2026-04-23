import base64
import os
from datetime import datetime, time

import cv2
import numpy as np
from django.conf import settings
from django.http import JsonResponse
from django.shortcuts import render
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.views import View
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET
from feat import Detector

from .models import CustomerEmotion, InterventionRecord

detector = Detector(device="cpu")

INTERVENTION_THRESHOLD = 70
MAX_FRAMES_FOR_INTERVENTION = 2
AU_RULES = [
    {
        "id": "wide_eyes",
        "feature": "AU05_r",
        "threshold": 0.55,
        "comparison": "gte",
        "message": "?¼ç??œå?è¼ƒå¤§ï¼Œå¯?ä?å¤§å??ˆè??®æ??–å??–èªª?ã€?,
    },
    {
        "id": "raised_brow",
        "feature": "AU02_r",
        "threshold": 0.35,
        "comparison": "gte",
        "message": "?‰æ?ä¸Šæ?ï¼Œå¯?½ä??‰ç??ï?ä¸»å??æ¬¡èªªæ???,
    },
    {
        "id": "lip_press",
        "feature": "AU23_r",
        "threshold": 0.30,
        "comparison": "gte",
        "message": "?´å?ç·Šé?ï¼Œé¡§å®¢å¯?½çŒ¶è±«ï??¯æ¨?¦æ›¿ä»?–¹æ¡ˆæ??ªæ???,
    },
]


def index(request):
    return render(request, "index.html")


@csrf_exempt
def detect_emotion(request):
    if request.method != "POST":
        return JsonResponse({"error": "Invalid request"}, status=400)

    image_data = request.POST.get("image")
    customer_id = request.POST.get("customer_id")

    if not customer_id:
        return JsonResponse({"error": "ç¼ºå? customer_idï¼Œè??æ–°?‹å??µæ¸¬"}, status=400)
    if not image_data:
        return JsonResponse({"error": "æ²’æ??¶åˆ°å½±å?è³‡æ?"}, status=400)

    try:
        header, imgstr = image_data.split(";base64,")
    except ValueError:
        return JsonResponse({"error": "å½±å?è³‡æ??¼å?ä¸æ­£ç¢?}, status=400)

    ext = header.split("/")[-1]
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    filename = f"{customer_id}_{timestamp}.{ext}"
    relative_path = f"customer_faces/{filename}"
    media_root = str(settings.MEDIA_ROOT)
    full_path = os.path.join(media_root, "customer_faces", filename)

    os.makedirs(os.path.dirname(full_path), exist_ok=True)
    img_binary = base64.b64decode(imgstr)
    with open(full_path, "wb") as file:
        file.write(img_binary)

    np_image = np.frombuffer(img_binary, np.uint8)
    decoded_image = cv2.imdecode(np_image, cv2.IMREAD_COLOR)
    temp_path = os.path.join(media_root, "temp_detect.jpg")
    cv2.imwrite(temp_path, decoded_image)

    faces = detector.detect_image([temp_path])
    if faces.empty:
        return JsonResponse({"error": "æ²’æ??µæ¸¬?°äºº?‰ï?è«‹èª¿?´é¡?­ä?ç½?}, status=400)

    emotions = faces.iloc[0][[
        "happiness", "sadness", "anger", "surprise", "fear", "disgust", "neutral"
    ]].to_dict()
    dominant = max(emotions, key=emotions.get)
    au_data = _extract_au_data(faces)

    sop_suggestions = {
        "happiness": "é¡§å®¢å¿ƒæ??‰æ?ï¼Œå¯ä¸»å??¨å»£é«˜å–®?¹å??æ??ƒå“¡æ´»å???,
        "sadness": "é¡§å®¢?…ç?ä½è½ï¼Œå»ºè­°æ?ä¾›è²¼å¿ƒé??·è??”åŠ©??,
        "anger": "é¡§å®¢?¯èƒ½ä¸æ»¿ï¼Œæ?ä¸»å??œå?ä¸¦æ?ä¾›è§£æ±ºæ–¹æ¡ˆã€?,
        "surprise": "é¡§å®¢å°æ–°äº‹ç‰©?Ÿè?è¶???¯æ¨ä»‹æ–°?¢å??–é?é©—æ´»?•ã€?,
        "fear": "é¡§å®¢?Ÿåˆ°ä¸å?ï¼Œå»ºè­°å¼·èª¿å??¨æ€§ä¸¦è£œå?ç¢ºå?è³‡è???,
        "disgust": "é¡§å®¢å°ç’°å¢ƒæ??†å??æ?ï¼Œæ?ç«‹å³èª¿æ•´?³å??–å…§å®¹ã€?,
        "neutral": "é¡§å®¢?…ç?ç©©å?ï¼Œå¯å¤šä??•ä»¥å°‹æ‰¾?·å”®æ©Ÿæ???,
    }
    sop_feedback = sop_suggestions.get(dominant, "?«ç„¡å»ºè­°")

    record = CustomerEmotion.objects.create(
        customer_id=customer_id,
        face_image=relative_path,
        image_path=relative_path,
        happiness=emotions.get("happiness", 0.0),
        sadness=emotions.get("sadness", 0.0),
        anger=emotions.get("anger", 0.0),
        surprise=emotions.get("surprise", 0.0),
        fear=emotions.get("fear", 0.0),
        disgust=emotions.get("disgust", 0.0),
        neutral=emotions.get("neutral", 0.0),
        emotion_data=emotions,
        au_data=au_data,
    )

    intervention_payload = _check_and_build_intervention(customer_id, record)

    response = {
        "dominant_emotion": dominant,
        "analysis_feedback": sop_feedback,
        "emotion_data": emotions,
        "customer_id": customer_id,
    }
    response.update(intervention_payload)
    return JsonResponse(response)


def report_view(request):
    return render(request, "report.html")


@require_GET
def report_data(request):
    date_str = request.GET.get("date")
    if not date_str:
        return JsonResponse({"status": "error", "message": "è«‹æ?ä¾›æ—¥??})

    selected_date = parse_date(date_str)
    if not selected_date:
        return JsonResponse({"status": "error", "message": "?¥æ??¼å??‰èª¤"})

    start_of_day = datetime.combine(selected_date, time.min)
    end_of_day = datetime.combine(selected_date, time.max)

    if settings.USE_TZ:
        current_tz = timezone.get_current_timezone()
        start_of_day = timezone.make_aware(start_of_day, current_tz)
        end_of_day = timezone.make_aware(end_of_day, current_tz)

    records = (
        CustomerEmotion.objects
        .filter(created_at__range=(start_of_day, end_of_day))
        .order_by("customer_id", "created_at")
    )
    if not records.exists():
        return JsonResponse({"status": "no_data", "message": "è©²æ—¥?Ÿæ??‰åµæ¸¬ç???})

    sessions = {}
    total_scores = []
    records_by_session = {}

    for record in records:
        emotions = record.emotion_data or {}
        satisfaction = _calculate_satisfaction(emotions)
        session = sessions.setdefault(record.customer_id, {
            "customer_id": record.customer_id,
            "points": [],
            "avg_score": 0.0,
        })
        session["points"].append({
            "time": record.created_at.strftime("%H:%M:%S"),
            "score": satisfaction,
        })
        records_by_session.setdefault(record.customer_id, []).append(record)
        total_scores.append(satisfaction)

    for session in sessions.values():
        scores = [point["score"] for point in session["points"]]
        session["avg_score"] = round(sum(scores) / len(scores), 2)

    daily_avg = round(sum(total_scores) / len(total_scores), 2)
    interventions = _evaluate_interventions(
        sessions,
        records_by_session,
        selected_date,
    )

    return JsonResponse({
        "status": "ok",
        "sessions": list(sessions.values()),
        "daily_avg": daily_avg,
        "interventions": interventions,
    })


class EmotionDetectionView(View):
    def get(self, request):
        return JsonResponse({'message': 'This is EmotionDetectionView'})


class EmotionHistoryView(View):
    def get(self, request):
        return JsonResponse({'message': 'This is EmotionHistoryView'})


def _calculate_satisfaction(emotions):
    positive = (
        emotions.get("happiness", 0.0) +
        emotions.get("surprise", 0.0) +
        0.5 * emotions.get("neutral", 0.0)
    )
    negative = (
        emotions.get("sadness", 0.0) +
        emotions.get("anger", 0.0) +
        emotions.get("fear", 0.0) +
        emotions.get("disgust", 0.0)
    )
    satisfaction = 50 + (positive - negative) * 50
    return max(0, min(100, round(satisfaction, 2)))


def _extract_au_data(faces):
    au_columns = [col for col in faces.columns if col.lower().startswith("au")]
    if not au_columns:
        return {}
    row = faces.iloc[0][au_columns]
    return {key: float(row[key]) for key in au_columns}


def _check_and_build_intervention(customer_id, current_record):
    recent_records = (
        CustomerEmotion.objects
        .filter(customer_id=customer_id)
        .order_by("-created_at")[:MAX_FRAMES_FOR_INTERVENTION]
    )
    if len(recent_records) < MAX_FRAMES_FOR_INTERVENTION:
        return {
            "needs_intervention": False,
            "special_suggestions": [],
            "frames_info": [],
        }

    recent_records = list(reversed(recent_records))
    scores = [_calculate_satisfaction(r.emotion_data or {}) for r in recent_records]
    average_score = round(sum(scores) / len(scores), 2)
    if average_score >= INTERVENTION_THRESHOLD:
        return {
            "needs_intervention": False,
            "special_suggestions": [],
            "frames_info": [],
        }

    frames_payload = []
    for record in recent_records:
        frames_payload.append({
            "image_path": record.image_path,
            "captured_at": record.created_at.strftime("%H:%M:%S"),
            "emotion_data": record.emotion_data or {},
            "au_data": record.au_data or {},
        })

    suggestions = _build_special_suggestions(frames_payload)
    InterventionRecord.objects.update_or_create(
        session_label=customer_id,
        analysis_date=current_record.created_at.date(),
        defaults={
            "average_score": average_score,
            "frames": frames_payload,
            "suggestions": suggestions,
            "needs_intervention": True,
        },
    )
    return {
        "needs_intervention": bool(suggestions),
        "special_suggestions": suggestions,
        "frames_info": frames_payload,
        "intervention_score": average_score,
    }


def _evaluate_interventions(sessions, records_by_session, analysis_date):
    interventions = []
    for session_id, session in sessions.items():
        points = session["points"]
        if len(points) < MAX_FRAMES_FOR_INTERVENTION:
            continue

        first_two_scores = [point["score"] for point in points[:MAX_FRAMES_FOR_INTERVENTION]]
        avg_score = round(sum(first_two_scores) / len(first_two_scores), 2)
        if avg_score >= INTERVENTION_THRESHOLD:
            continue

        related_records = records_by_session.get(session_id, [])[:MAX_FRAMES_FOR_INTERVENTION]
        if len(related_records) < MAX_FRAMES_FOR_INTERVENTION:
            continue

        frames_payload = []
        for record in related_records:
            frames_payload.append({
                "image_path": record.image_path,
                "captured_at": record.created_at.strftime("%H:%M:%S"),
                "emotion_data": record.emotion_data or {},
                "au_data": record.au_data or {},
            })

        suggestions = _build_special_suggestions(frames_payload)
        if not suggestions:
            continue

        InterventionRecord.objects.update_or_create(
            session_label=session_id,
            analysis_date=analysis_date,
            defaults={
                "average_score": avg_score,
                "frames": frames_payload,
                "suggestions": suggestions,
                "needs_intervention": True,
            },
        )
        interventions.append({
            "session_id": session_id,
            "average_score": avg_score,
            "suggestions": suggestions,
            "frames": frames_payload,
        })

    return interventions


def _build_special_suggestions(frames_payload):
    results = []
    for rule in AU_RULES:
        for index, frame in enumerate(frames_payload, start=1):
            value = float(frame["au_data"].get(rule["feature"], 0.0))
            if rule["comparison"] == "gte" and value >= rule["threshold"]:
                results.append(f"{rule['message']} (Frame {index}ï¼Œ{rule['feature']}={value:.2f})")
            elif rule["comparison"] == "lte" and value <= rule["threshold"]:
                results.append(f"{rule['message']} (Frame {index}ï¼Œ{rule['feature']}={value:.2f})")
    return results

