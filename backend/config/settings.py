from pathlib import Path
import os
import sys
from dotenv import load_dotenv
from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent
# .env используется как локальный fallback и не должен перетирать реальные
# переменные окружения (Railway/K8s/CI), иначе можно случайно подключиться к
# localhost вместо DATABASE_URL провайдера.
load_dotenv(BASE_DIR / ".env", override=False)

SECRET_KEY = os.getenv("SECRET_KEY", "django-insecure-s)66ib*p(f+^813d+^2do6@*w4b^f57g787=hv)@lu7t=g^7!k")
DEBUG = os.getenv("DEBUG", "True") == "True"
ALLOWED_HOSTS = [h.strip() for h in os.getenv("ALLOWED_HOSTS", "localhost,127.0.0.1").split(",") if h.strip()]
if ".trycloudflare.com" not in ALLOWED_HOSTS:
    ALLOWED_HOSTS.append(".trycloudflare.com")

# На Railway публичный домен сервиса доступен в RAILWAY_PUBLIC_DOMAIN.
# Добавляем его автоматически, чтобы health-check и публичный URL работали без
# ручного управления ALLOWED_HOSTS на каждом редеплое.
_railway_domain = os.getenv("RAILWAY_PUBLIC_DOMAIN", "").strip()
if _railway_domain and _railway_domain not in ALLOWED_HOSTS:
    ALLOWED_HOSTS.append(_railway_domain)

# Railway healthcheck и публичный URL всегда идут на хост вида
# <service>-<id>.up.railway.app. Если RAILWAY_PUBLIC_DOMAIN по какой-то
# причине не попал в env до первого запроса, без суффикса Django даёт
# DisallowedHost (400) — в логах Railway это часто выглядит как «service
# unavailable» на /healthz/.
_on_railway = bool(os.getenv("RAILWAY_ENVIRONMENT") or os.getenv("RAILWAY_PROJECT_ID"))
if _on_railway and ".up.railway.app" not in ALLOWED_HOSTS:
    ALLOWED_HOSTS.append(".up.railway.app")

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
    # Healthcheck-перехватчик ДО SecurityMiddleware: Railway healthcheck
    # приходит с внутренним Host, которого нет в ALLOWED_HOSTS, и без этого
    # Django ответит 400 DisallowedHost.
    "config.health.HealthcheckMiddleware",
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


def _apply_postgres_connection_hardening(db: dict) -> None:
    """Меньше обрывов после рестарта Postgres / простоя соединения."""
    eng = (db.get("ENGINE") or "").lower()
    if "postgresql" not in eng and "postgis" not in eng:
        return
    db.setdefault("CONN_MAX_AGE", int(os.getenv("DB_CONN_MAX_AGE", "600") or "600"))
    db["CONN_HEALTH_CHECKS"] = True
    opts = db.setdefault("OPTIONS", {})
    if not isinstance(opts, dict):
        return
    timeout = int(os.getenv("DB_CONNECT_TIMEOUT", "10") or "10")
    opts.setdefault("connect_timeout", timeout)


# Только PostgreSQL (DATABASE_URL с Railway или блок DB_* как в docker-compose.prod.yml).
_database_url = os.getenv("DATABASE_URL", "").strip()
if _database_url:
    low = _database_url.lower()
    if "sqlite" in low or low.startswith("file:") or ":memory:" in low:
        raise ImproperlyConfigured(
            "Поддерживается только PostgreSQL. DATABASE_URL не должен указывать на SQLite или file:/memory: "
            "— удалите переменную из окружения или задайте postgresql://… Можно оставить только DB_* без DATABASE_URL."
        )

    import dj_database_url

    _is_postgres_url = _database_url.lower().startswith(("postgres://", "postgresql://", "postgis://"))
    # На Railway Postgres почти всегда требует SSL. Если URL уже содержит
    # sslmode=require, дублирование не мешает. Локально с DATABASE_URL без SSL
    # выставьте DB_SSL_REQUIRE=false.
    _db_ssl_default = "true" if _is_postgres_url else "false"
    _db_ssl_require = os.getenv("DB_SSL_REQUIRE", _db_ssl_default).lower() == "true"
    _db_parse_kwargs = {"conn_max_age": int(os.getenv("DB_CONN_MAX_AGE", "600") or "600")}
    if _is_postgres_url:
        _db_parse_kwargs["ssl_require"] = _db_ssl_require
    _default_db = dj_database_url.parse(_database_url, **_db_parse_kwargs)
    _apply_postgres_connection_hardening(_default_db)
    DATABASES = {"default": _default_db}
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": os.getenv("DB_NAME", "dashboard"),
            "USER": os.getenv("DB_USER", "dashboard"),
            "PASSWORD": os.getenv("DB_PASSWORD", "dashboard"),
            "HOST": os.getenv("DB_HOST", "localhost"),
            "PORT": os.getenv("DB_PORT", "5432"),
            "CONN_MAX_AGE": int(os.getenv("DB_CONN_MAX_AGE", "600") or "600"),
            "CONN_HEALTH_CHECKS": True,
            "OPTIONS": {
                "connect_timeout": int(os.getenv("DB_CONNECT_TIMEOUT", "10") or "10"),
            },
        }
    }

# Краткий лог при старте (без пароля): какой движок реально используется.
_db_cfg = DATABASES["default"]
_engine = str(_db_cfg.get("ENGINE", ""))
_db_name = str(_db_cfg.get("NAME", ""))
print(
    f"[django settings] DB engine={_engine.split('.')[-1]} name={_db_name!r} "
    f"host={_db_cfg.get('HOST', '')!r}",
    file=sys.stderr,
)

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
# Манифест-хранилище WhiteNoise требует выполненного collectstatic и хеширует
# имена файлов. На локалке (DEBUG=True) collectstatic не запускают, поэтому
# подключаем его только в проде, иначе админка падает с "Missing staticfiles
# manifest entry".
if not DEBUG:
    STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# CORS / CSRF
_extra_origins = [o.strip() for o in os.getenv("CORS_EXTRA_ORIGINS", "").split(",") if o.strip()]
CORS_ALLOWED_ORIGINS = [
    "http://localhost:5173",
    "http://localhost:3000",
] + _extra_origins
CORS_ALLOW_ALL_ORIGINS = DEBUG

# CSRF_EXTRA_ORIGINS — публичные origin'ы (VPS, кастомный домен, второй
# Railway-сервис со SPA).
_csrf_extra = [o.strip() for o in os.getenv("CSRF_EXTRA_ORIGINS", "").split(",") if o.strip()]

CSRF_TRUSTED_ORIGINS = [
    "http://localhost:5173",
    "http://localhost:3000",
    "http://localhost:8000",
] + _csrf_extra
if "https://*.trycloudflare.com" not in CSRF_TRUSTED_ORIGINS:
    CSRF_TRUSTED_ORIGINS.append("https://*.trycloudflare.com")
if _railway_domain:
    railway_https = f"https://{_railway_domain}"
    if railway_https not in CSRF_TRUSTED_ORIGINS:
        CSRF_TRUSTED_ORIGINS.append(railway_https)
    if railway_https not in CORS_ALLOWED_ORIGINS:
        CORS_ALLOWED_ORIGINS.append(railway_https)

# Отдельный публичный домен фронтенда на Railway (второй сервис). Браузер
# открывает SPA на https://<frontend>, axios ходит на https://<backend>
# (VITE_API_URL) — без этого origin в CORS/CSRF Django отрежет запросы.
# Значение: только хост (xxx.up.railway.app) или полный URL с https://
_railway_fe = os.getenv("RAILWAY_FRONTEND_PUBLIC_DOMAIN", "").strip()
if _railway_fe:
    _fe_host = _railway_fe.rstrip("/")
    for _pfx in ("https://", "http://"):
        if _fe_host.lower().startswith(_pfx):
            _fe_host = _fe_host[len(_pfx) :]
            break
    _fe_schemes = ("https",) if not DEBUG else ("https", "http")
    for _sch in _fe_schemes:
        _fe_origin = f"{_sch}://{_fe_host}"
        if _fe_origin not in CORS_ALLOWED_ORIGINS:
            CORS_ALLOWED_ORIGINS.append(_fe_origin)
        if _fe_origin not in CSRF_TRUSTED_ORIGINS:
            CSRF_TRUSTED_ORIGINS.append(_fe_origin)

# Railway: TLS на edge, до контейнера — HTTP. Без этого Django считает
# запросы небезопасными и ломаются редиректы/CSRF для админки.
if os.getenv("RAILWAY_PUBLIC_DOMAIN", "").strip() or os.getenv("RAILWAY_ENVIRONMENT", "").strip():
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    USE_X_FORWARDED_HOST = True

YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY", "")

# ── Browser (TikTok / Instagram fallback via Playwright) ─────────────────────
# BROWSER_HEADLESS=true  — headless Chromium for server deployment
# BROWSER_STATE_FILE     — куда сохранить куки setup_tiktok_auth (локально). В Docker
#                          рабочий путь для воркера TikTok — <BROWSER_PROFILE_DIR>/tiktok_state.json
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
