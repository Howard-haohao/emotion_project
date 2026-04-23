import os
from pathlib import Path

# 專案根目錄
BASE_DIR = Path(__file__).resolve().parent.parent

# 安全金鑰 (正式上線時建議改用環境變數)
SECRET_KEY = 'XXX'

# 除錯模式
DEBUG = True

ALLOWED_HOSTS = ['*']

# 應用程式列表
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    
    # 你的核心 App
    'emotion_detection',
    
    # 第三方套件
    'rest_framework',
    'django_q',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'emotion_project.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'emotion_detection' / 'templates'], # 確保能找到 templates
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'emotion_project.wsgi.application'

# 資料庫設定 (MySQL)
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.mysql',
        'NAME': 'emotion',
        'USER': 'U1133029',
        'PASSWORD': 'U1133029',
        'HOST': 'localhost',
        'PORT': '3306',
    }
}

# 密碼驗證
AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]

# --- 國際化與時區 ---
LANGUAGE_CODE = 'en-us'

# 設定為台北時間
TIME_ZONE = 'Asia/Taipei'

# [重要修改] 開啟時區支援，確保每日流水號重置邏輯正確
USE_I18N = True
USE_TZ = True

# --- 靜態與媒體檔案 ---
STATIC_URL = 'static/'
STATICFILES_DIRS = [BASE_DIR / 'static']

MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

# --- [新增] 登入系統導向與 Session 控制 ---
# 未登入時導向的網址
LOGIN_URL = '/login/'
# 登入成功後導向的網址
LOGIN_REDIRECT_URL = '/'
# 登出後導向的網址
LOGOUT_REDIRECT_URL = '/login/'

# [關鍵修改] 關閉瀏覽器即登出 (符合你的第 3 點要求)
SESSION_EXPIRE_AT_BROWSER_CLOSE = True
# (可選) Session 有效期設為 30 分鐘，避免掛網太久
# SESSION_COOKIE_AGE = 1800 

# 允許同源 iframe (解決報表無法顯示的問題)
X_FRAME_OPTIONS = 'SAMEORIGIN'

# --- OpenAI 設定 ---
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")

# --- Django Q (背景任務) ---
Q_CLUSTER = {
    "name": "emotion_queue",
    "workers": 2,
    "timeout": 40,
    "retry": 120,
    "queue_limit": 50,
    "bulk": 10,
    "orm": "default",
}

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
