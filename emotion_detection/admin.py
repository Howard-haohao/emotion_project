from django.contrib import admin
from .models import CustomerEmotion, InterventionRecord

@admin.register(CustomerEmotion)
class CustomerEmotionAdmin(admin.ModelAdmin):
    # list_display 可以顯示 @property，這沒問題
    list_display = ('customer_id', 'dominant_emotion', 'score', 'created_at')
    
    # [注意] list_filter 只能放資料庫有的欄位，不能放 @property
    # 所以這裡只放 'created_at'，不要放 score 或 dominant_emotion
    list_filter = ('created_at',) 
    
    search_fields = ('customer_id',)
    readonly_fields = ('created_at',)

@admin.register(InterventionRecord)
class InterventionRecordAdmin(admin.ModelAdmin):
    list_display = ('session_label', 'emotion_label', 'average_score', 'source', 'created_at')
    
    # emotion_label 和 source 是真實欄位，可以篩選
    list_filter = ('source', 'emotion_label', 'created_at') 
    
    search_fields = ('session_label', 'suggestions')
    readonly_fields = ('created_at', 'updated_at')