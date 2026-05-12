from pathlib import Path
import os
import sys

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env", override=False)

SECRET_KEY = os.getenv("SECRET_KEY", "django-insecure-subs-dev-only-change-me")
DEBUG = os.getenv("DEBUG", "True") == "True"
ALLOWED_HOSTS = [h.strip() for h in os.getenv("ALLOWED_HOSTS", "localhost,127.0.0.1").split(",") if h.strip()]
if ".trycloudflare.com" not in ALLOWED_HOSTS:
    ALLOWED_HOSTS.append(".trycloudflare.com")
if ".loca.lt" not in ALLOWED_HOSTS:
    ALLOWED_HOSTS.append(".loca.lt")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "corsheaders",
    "subscribers.apps.SubscribersConfig",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

_database_url = os.getenv("DATABASE_URL", "").strip()

# Базовый URL API дашборда (синхронизация, съём аудитории, вкладка «Авторизация» на фронте).
DASHBOARD_API_URL = os.getenv("DASHBOARD_API_URL", "http://127.0.0.1:8000").rstrip("/")

import dj_database_url

if not _database_url:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "subs.sqlite3",
        }
    }
elif _database_url.lower().startswith("sqlite"):
    DATABASES = {"default": dj_database_url.parse(_database_url)}
else:
    _default_db = dj_database_url.parse(
        _database_url,
        conn_max_age=int(os.getenv("DB_CONN_MAX_AGE", "600") or "600"),
    )
    _default_db.setdefault("CONN_HEALTH_CHECKS", True)
    if "postgresql" in str(_default_db.get("ENGINE", "")).lower():
        _default_db.setdefault("OPTIONS", {})
        if isinstance(_default_db["OPTIONS"], dict):
            _default_db["OPTIONS"].setdefault(
                "connect_timeout",
                int(os.getenv("DB_CONNECT_TIMEOUT", "10") or "10"),
            )
    DATABASES = {"default": _default_db}

AUTH_PASSWORD_VALIDATORS = []

LANGUAGE_CODE = "ru-ru"
TIME_ZONE = "Europe/Moscow"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

_cors = [o.strip() for o in os.getenv("CORS_ALLOWED_ORIGINS", "").split(",") if o.strip()]
CORS_ALLOWED_ORIGINS = _cors or [
    "http://127.0.0.1:5180",
    "http://localhost:5180",
]
# Фронт на https://*.trycloudflare.com, API на другом порту / другом туннеле — без regex CORS режет ответы.
CORS_ALLOWED_ORIGIN_REGEXES = [
    r"^https://[a-z0-9-]+\.trycloudflare\.com$",
    r"^https://[a-z0-9-]+\.loca\.lt$",
]
CORS_ALLOW_CREDENTIALS = True

REST_FRAMEWORK = {
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_PARSER_CLASSES": ["rest_framework.parsers.JSONParser"],
    # Без django.contrib.auth: иначе DRF тянет AnonymousUser и падает с RuntimeError на /api/…
    "DEFAULT_AUTHENTICATION_CLASSES": [],
    "UNAUTHENTICATED_USER": None,
}

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
# Quick Tunnel / nginx шлёт Host исходного HTTPS; иначе absolute URL в ответах и проверки Host ломаются.
USE_X_FORWARDED_HOST = True

_db = DATABASES["default"]
print(
    f"[subs] engine={_db.get('ENGINE')!r} name={_db.get('NAME')!r} host={_db.get('HOST')!r}",
    file=sys.stderr,
)
