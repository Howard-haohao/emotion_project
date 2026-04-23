from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path('admin/', admin.site.urls),
    # 將所有根目錄請求轉交給 emotion_detection App
    path('', include('emotion_detection.urls')),
]

# 在開發模式下，讓 Django 協助提供上傳的圖片檔案 (人臉截圖)
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)