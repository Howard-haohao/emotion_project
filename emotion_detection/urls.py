from django.urls import path
from . import views

urlpatterns = [
    # --- 頁面路由 (Pages) ---
    path('', views.index, name='index'),
    path('monitor/', views.index, name='monitor'), # SPA 重新整理支援
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('report/', views.report_view, name='report_view'),

    # --- 員工管理 (Management) ---
    path('manage_employees/', views.manage_employees, name='manage_employees'),
    path('add_employee/', views.add_employee, name='add_employee'),
    path('delete_employee/<int:user_id>/', views.delete_employee, name='delete_employee'),
    path('profile/', views.profile_view, name='profile'),

    # --- 功能 API (Functional APIs) ---
    path('detect_emotion/', views.detect_emotion, name='detect_emotion'),
    path('get_new_session_id/', views.get_new_session_id, name='get_new_session_id'),
    path('marketing_status/', views.marketing_status, name='marketing_status'),
    path('report_data/', views.report_data, name='report_data'),
    
    # 保留舊路由 (視圖類別)
    path('view/', views.EmotionDetectionView.as_view(), name='emotion_view'),
    path('history/', views.EmotionHistoryView.as_view(), name='emotion_history'),
]