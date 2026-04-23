# import base64
# import os
# from datetime import datetime, time

# import cv2
# import numpy as np
# from django.conf import settings
# from django.http import JsonResponse
# from django.shortcuts import render
# from django.utils import timezone
# from django.utils.dateparse import parse_date
# from django.views import View
# from django.views.decorators.csrf import csrf_exempt
# from django.views.decorators.http import require_GET
# from feat import Detector

# from .models import CustomerEmotion

# detector = Detector(device="cpu")


# def index(request):
#     return render(request, "index.html")


# @csrf_exempt
# def detect_emotion(request):
#     if request.method != "POST":
#         return JsonResponse({"error": "Invalid request"}, status=400)

#     image_data = request.POST.get("image")
#     customer_id = request.POST.get("customer_id")

#     if not customer_id:
#         return JsonResponse({"error": "缺少 customer_id，請重新開始偵測。"}, status=400)
#     if not image_data:
#         return JsonResponse({"error": "沒有收到影像資料。"}, status=400)

#     try:
#         header, imgstr = image_data.split(";base64,")
#     except ValueError:
#         return JsonResponse({"error": "影像資料格式不正確。"}, status=400)

#     ext = header.split("/")[-1]
#     timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
#     filename = f"{customer_id}_{timestamp}.{ext}"
#     relative_path = f"customer_faces/{filename}"
#     media_root = str(settings.MEDIA_ROOT)
#     full_path = os.path.join(media_root, "customer_faces", filename)

#     os.makedirs(os.path.dirname(full_path), exist_ok=True)
#     img_binary = base64.b64decode(imgstr)
#     with open(full_path, "wb") as file:
#         file.write(img_binary)

#     np_image = np.frombuffer(img_binary, np.uint8)
#     decoded_image = cv2.imdecode(np_image, cv2.IMREAD_COLOR)
#     temp_path = os.path.join(media_root, "temp_detect.jpg")
#     cv2.imwrite(temp_path, decoded_image)

#     faces = detector.detect_image([temp_path])
#     if faces.empty:
#         return JsonResponse({"error": "沒有偵測到人臉，請調整鏡頭位置。"}, status=400)

#     emotions = faces.iloc[0][[
#         "happiness", "sadness", "anger", "surprise", "fear", "disgust", "neutral"
#     ]].to_dict()
#     dominant = max(emotions, key=emotions.get)

#     suggestions = {
#         "happiness": "顧客心情愉悅，可加碼推廣高單價商品或會員活動。",
#         "sadness": "顧客情緒低落，建議提供貼心問候與協助。",
#         "anger": "顧客可能不滿，請主動關心並提供補償方案。",
#         "surprise": "顧客對新刺激有反應，可推播新品或體驗活動。",
#         "fear": "顧客感到不安，請建立安全感並提供明確資訊。",
#         "disgust": "顧客對目前情境反感，建議立即調整服務內容。",
#         "neutral": "顧客情緒穩定，可多發問以尋找推銷機會。",
#     }
#     feedback = suggestions.get(dominant, "無法辨識情緒")

#     CustomerEmotion.objects.create(
#         customer_id=customer_id,
#         face_image=relative_path,
#         image_path=relative_path,
#         happiness=emotions.get("happiness", 0.0),
#         sadness=emotions.get("sadness", 0.0),
#         anger=emotions.get("anger", 0.0),
#         surprise=emotions.get("surprise", 0.0),
#         fear=emotions.get("fear", 0.0),
#         disgust=emotions.get("disgust", 0.0),
#         neutral=emotions.get("neutral", 0.0),
#         emotion_data=emotions,
#     )

#     return JsonResponse({
#         "dominant_emotion": dominant,
#         "analysis_feedback": feedback,
#         "emotion_data": emotions,
#         "customer_id": customer_id,
#     })


# def report_view(request):
#     return render(request, "report.html")


# @require_GET
# def report_data(request):
#     date_str = request.GET.get("date")
#     if not date_str:
#         return JsonResponse({"status": "error", "message": "請提供日期"})

#     selected_date = parse_date(date_str)
#     if not selected_date:
#         return JsonResponse({"status": "error", "message": "日期格式錯誤"})

#     start_of_day = datetime.combine(selected_date, time.min)
#     end_of_day = datetime.combine(selected_date, time.max)

#     if settings.USE_TZ:
#         current_tz = timezone.get_current_timezone()
#         start_of_day = timezone.make_aware(start_of_day, current_tz)
#         end_of_day = timezone.make_aware(end_of_day, current_tz)

#     records = CustomerEmotion.objects.filter(created_at__range=(start_of_day, end_of_day))
#     if not records.exists():
#         return JsonResponse({"status": "no_data", "message": "指定日期沒有偵測紀錄"})

#     summary = {
#         "happiness": 0, "sadness": 0, "anger": 0, "surprise": 0,
#         "fear": 0, "disgust": 0, "neutral": 0
#     }
#     for record in records:
#         summary["happiness"] += record.happiness
#         summary["sadness"] += record.sadness
#         summary["anger"] += record.anger
#         summary["surprise"] += record.surprise
#         summary["fear"] += record.fear
#         summary["disgust"] += record.disgust
#         summary["neutral"] += record.neutral

#     total = sum(summary.values())
#     percentage = {k: round((v / total) * 100, 2) if total else 0 for k, v in summary.items()}

#     return JsonResponse({"status": "ok", "emotion_summary": percentage})


# class EmotionDetectionView(View):
#     def get(self, request):
#         return JsonResponse({'message': 'This is EmotionDetectionView'})


# class EmotionHistoryView(View):
#     def get(self, request):
#         return JsonResponse({'message': 'This is EmotionHistoryView'})
