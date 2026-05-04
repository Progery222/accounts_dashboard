from pathlib import Path
import os
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

SECRET_KEY = os.getenv("SECRET_KEY", "django-insecure-s)66ib*p(f+^813d+^2do6@*w4b^f57g787=hv)@lu7t=g^7!k")
DEBUG = os.getenv("DEBUG", "True") == "True"
ALLOWED_HOSTS = [h.strip() for h in os.getenv("ALLOWED_HOSTS", "localhost,127.0.0.1").split(",") if h.strip()]

# На Railway публичный домен сервиса доступен в RAILWAY_PUBLIC_DOMAIN.
# Добавляем его автоматически, чтобы health-check и публичный URL работали без
# ручного управления ALLOWED_HOSTS на каждом редеплое.
_railway_domain = os.getenv("RAILWAY_PUBLIC_DOMAIN", "").strip()
if _railway_domain and _railway_domain not in ALLOWED_HOSTS:
    ALLOWED_HOSTS.append(_railway_domain)

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "corsheaders",
    "accounts",
    "tiktok_app",
]

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    # WhiteNoise отдаёт статику в проде (Django admin) без отдельного nginx.
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

# Postgres: на Railway автоматически выставляется DATABASE_URL.
# Локально/в Docker compose используем DB_* envs (psycopg2 нативно).
_database_url = os.getenv("DATABASE_URL", "").strip()
if _database_url:
    import dj_database_url

    DATABASES = {
        "default": dj_database_url.parse(
            _database_url,
            conn_max_age=600,
            ssl_require=os.getenv("DB_SSL_REQUIRE", "false").lower() == "true",
        )
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": os.getenv("DB_NAME", "dashboard"),
            "USER": os.getenv("DB_USER", "dashboard"),
            "PASSWORD": os.getenv("DB_PASSWORD", "dashboard"),
            "HOST": os.getenv("DB_HOST", "localhost"),
            "PORT": os.getenv("DB_PORT", "5432"),
        }
    }

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "ru-ru"
TIME_ZONE = "Europe/Moscow"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# CORS / CSRF
_extra_origins = [o.strip() for o in os.getenv("CORS_EXTRA_ORIGINS", "").split(",") if o.strip()]
CORS_ALLOWED_ORIGINS = [
    "http://localhost:5173",
    "http://localhost:3000",
] + _extra_origins
CORS_ALLOW_ALL_ORIGINS = DEBUG

CSRF_TRUSTED_ORIGINS = [
    "http://localhost:5173",
    "http://localhost:3000",
    "http://localhost:8000",
]
if _railway_domain:
    railway_https = f"https://{_railway_domain}"
    if railway_https not in CSRF_TRUSTED_ORIGINS:
        CSRF_TRUSTED_ORIGINS.append(railway_https)
    if railway_https not in CORS_ALLOWED_ORIGINS:
        CORS_ALLOWED_ORIGINS.append(railway_https)

YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY", "")

# ── Browser (TikTok / Instagram fallback via Playwright) ─────────────────────
# BROWSER_HEADLESS=true  — headless Chromium for server deployment
# BROWSER_STATE_FILE     — path to exported cookies JSON (from setup_tiktok_auth)
# BROWSER_PROFILE_DIR    — persistent profile dir for local dev (auto-detected if empty)
BROWSER_HEADLESS = os.getenv("BROWSER_HEADLESS", "false").lower() == "true"
BROWSER_STATE_FILE = os.getenv("BROWSER_STATE_FILE", "")
BROWSER_PROFILE_DIR = os.getenv("BROWSER_PROFILE_DIR", "")
TIKTOK_USERNAME = os.getenv("TIKTOK_USERNAME", "")
TIKTOK_PASSWORD = os.getenv("TIKTOK_PASSWORD", "")

# ── Instagram (instaloader — no browser needed) ───────────────────────────────
INSTAGRAM_USERNAME = os.getenv("INSTAGRAM_USERNAME", "")
INSTAGRAM_PASSWORD = os.getenv("INSTAGRAM_PASSWORD", "")
INSTAGRAM_SESSION_FILE = os.getenv("INSTAGRAM_SESSION_FILE", "")

# ── Facebook ───────────────────────────────────────────────────────────────────
# ВНИМАНИЕ: пароли ТОЛЬКО через .env / переменные окружения. Никаких дефолтов.
FACEBOOK_EMAIL    = os.getenv("FACEBOOK_EMAIL", "")
FACEBOOK_PASSWORD = os.getenv("FACEBOOK_PASSWORD", "")

# ── Telegram (Telethon MTProto API) ───────────────────────────────────────────
# API credentials: https://my.telegram.org → API development tools
TELEGRAM_API_ID = os.getenv("TELEGRAM_API_ID", "")
TELEGRAM_API_HASH = os.getenv("TELEGRAM_API_HASH", "")
TELEGRAM_PHONE = os.getenv("TELEGRAM_PHONE", "")
# Session file created by: python manage.py setup_telegram_auth
TELEGRAM_SESSION_FILE = os.getenv("TELEGRAM_SESSION_FILE", "telegram.session")

# Пауза между аккаунтами в POST /api/accounts/refresh_all/ (секунды). 0,0 — без паузы.
# Для снижения нагрузки на платформы можно задать, например, REFRESH_ALL_DELAY_MIN=5 REFRESH_ALL_DELAY_MAX=12.
REFRESH_ALL_DELAY_MIN = float(os.getenv("REFRESH_ALL_DELAY_MIN", "0") or "0")
REFRESH_ALL_DELAY_MAX = float(os.getenv("REFRESH_ALL_DELAY_MAX", "0") or "0")

REST_FRAMEWORK = {
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_AUTHENTICATION_CLASSES": [],
    "DEFAULT_PERMISSION_CLASSES": [],
}
