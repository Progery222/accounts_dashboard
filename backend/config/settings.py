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

# Чужой DATABASE_URL в окружении процесса (IDE/терминал) при override=False
# перебивает значение из .env — сбрасываем только не-Postgres URL и подгружаем .env снова.
_raw_db_url = os.getenv("DATABASE_URL", "").strip().lower()
if _raw_db_url and not _raw_db_url.startswith(("postgres://", "postgresql://", "postgis://")):
    os.environ.pop("DATABASE_URL", None)
    load_dotenv(BASE_DIR / ".env", override=False)

# Отдельные файлы настроек Playwright-воркеров (аккаунты vs Subs) — не обязаны совпадать с backend/.env
load_dotenv(BASE_DIR / "config" / "worker_accounts.env", override=False)
load_dotenv(BASE_DIR / "config" / "worker_subs.env", override=False)

try:
    from platforms.worker_utils import normalize_playwright_browsers_env

    _pw_browsers = normalize_playwright_browsers_env(mutate_os_environ=True)
    if _pw_browsers:
        print(
            f"[django settings] PLAYWRIGHT_BROWSERS_PATH={_pw_browsers}",
            file=sys.stderr,
        )
except Exception as _pw_exc:
    print(f"[django settings] playwright env normalize failed: {_pw_exc}", file=sys.stderr)

SECRET_KEY = os.getenv("SECRET_KEY", "django-insecure-s)66ib*p(f+^813d+^2do6@*w4b^f57g787=hv)@lu7t=g^7!k")
DEBUG = os.getenv("DEBUG", "True") == "True"
ALLOWED_HOSTS = [h.strip() for h in os.getenv("ALLOWED_HOSTS", "localhost,127.0.0.1").split(",") if h.strip()]
if ".trycloudflare.com" not in ALLOWED_HOSTS:
    ALLOWED_HOSTS.append(".trycloudflare.com")
if ".loca.lt" not in ALLOWED_HOSTS:
    ALLOWED_HOSTS.append(".loca.lt")

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
    # 0 = новое соединение на каждый запрос ORM в потоке (нужно для долгого Playwright).
    db.setdefault("CONN_MAX_AGE", int(os.getenv("DB_CONN_MAX_AGE", "0") or "0"))
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
    if not low.startswith(("postgres://", "postgresql://", "postgis://")):
        raise ImproperlyConfigured(
            "Поддерживается только PostgreSQL: DATABASE_URL должен начинаться с postgresql://, postgres:// или postgis://. "
            "Или удалите DATABASE_URL и задайте подключение через переменные DB_*."
        )

    import dj_database_url

    _is_postgres_url = _database_url.lower().startswith(("postgres://", "postgresql://", "postgis://"))
    # На Railway Postgres почти всегда требует SSL. Если URL уже содержит
    # sslmode=require, дублирование не мешает. Локально с DATABASE_URL без SSL
    # выставьте DB_SSL_REQUIRE=false.
    _db_ssl_default = "true" if _is_postgres_url else "false"
    _db_ssl_require = os.getenv("DB_SSL_REQUIRE", _db_ssl_default).lower() == "true"
    _db_parse_kwargs = {"conn_max_age": int(os.getenv("DB_CONN_MAX_AGE", "0") or "0")}
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
            "CONN_MAX_AGE": int(os.getenv("DB_CONN_MAX_AGE", "0") or "0"),
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

MEDIA_URL = "/media/"
MEDIA_ROOT = Path(os.getenv("MEDIA_ROOT", str(BASE_DIR / "media")))
# Манифест-хранилище WhiteNoise требует выполненного collectstatic и хеширует
# имена файлов. На локалке (DEBUG=True) collectstatic не запускают, поэтому
# подключаем его только в проде, иначе админка падает с "Missing staticfiles
# manifest entry".
if not DEBUG:
    STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Links (короткие ссылки / клики из bio) — см. docs/API.md в репозитории links
LINKS_API_URL = os.getenv("LINKS_API_URL", "").strip().rstrip("/")
LINKS_API_TOKEN = os.getenv("LINKS_API_TOKEN", "").strip()
LINKS_API_TIMEOUT = float(os.getenv("LINKS_API_TIMEOUT", "25") or "25")


def _optional_env_bool(name: str) -> bool | None:
    raw = (os.getenv(name) or "").strip().lower()
    if raw in {"1", "true", "yes", "on", "y"}:
        return True
    if raw in {"0", "false", "no", "off", "n"}:
        return False
    return None


def _optional_env_abs_path(name: str) -> Path | None:
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return None
    return Path(raw).expanduser().resolve()


# Playwright: пул демонов для дашборда (refresh, AccountsStats, съём аудитории по API accounts).
# Профиль и headless — ACCOUNTS_BROWSER_* (файл backend/config/worker_accounts.env).
# Приложение «Подписчики» — отдельный репозиторий ../subs (свой Django на :8010).
ACCOUNTS_BROWSER_PROFILE_DIR = _optional_env_abs_path("ACCOUNTS_BROWSER_PROFILE_DIR")
ACCOUNTS_BROWSER_HEADLESS = _optional_env_bool("ACCOUNTS_BROWSER_HEADLESS")

# Автообновление / refresh_all: поднять Playwright-демоны по всем платформам батча в начале.
# False — отложенный старт (одно окно при первом запросе; удобно на headless-сервере).
_ar_prewarm = _optional_env_bool("ACCOUNTS_AUTOREFRESH_PREWARM_PLAYWRIGHT")
ACCOUNTS_AUTOREFRESH_PREWARM_PLAYWRIGHT = True if _ar_prewarm is None else _ar_prewarm

# CORS / CSRF
_extra_origins = [o.strip() for o in os.getenv("CORS_EXTRA_ORIGINS", "").split(",") if o.strip()]
CORS_ALLOWED_ORIGINS = [
    "http://localhost:5173",
    "http://localhost:5174",
    "http://127.0.0.1:5174",
    "http://localhost:5180",
    "http://127.0.0.1:5180",
    "http://localhost:3000",
] + _extra_origins
CORS_ALLOW_ALL_ORIGINS = DEBUG
# При DEBUG=False список выше не покрывает эфемерные Quick Tunnel. Если фронт и API
# на разных *.trycloudflare.com (или localStorage new_frontend_api_base на другой
# origin), без regex браузер режет CORS. Один туннель с path /api → :8000 — same-origin, regex не мешает.
CORS_ALLOWED_ORIGIN_REGEXES = [
    r"^https://[a-z0-9-]+\.trycloudflare\.com$",
    r"^https://[a-z0-9-]+\.loca\.lt$",
]

# CSRF_EXTRA_ORIGINS — публичные origin'ы (VPS, кастомный домен, второй
# Railway-сервис со SPA).
_csrf_extra = [o.strip() for o in os.getenv("CSRF_EXTRA_ORIGINS", "").split(",") if o.strip()]

CSRF_TRUSTED_ORIGINS = [
    "http://localhost:5173",
    "http://localhost:5174",
    "http://127.0.0.1:5174",
    "http://localhost:5180",
    "http://127.0.0.1:5180",
    "http://localhost:3000",
    "http://localhost:8000",
] + _csrf_extra
if "https://*.trycloudflare.com" not in CSRF_TRUSTED_ORIGINS:
    CSRF_TRUSTED_ORIGINS.append("https://*.trycloudflare.com")
if "https://*.loca.lt" not in CSRF_TRUSTED_ORIGINS:
    CSRF_TRUSTED_ORIGINS.append("https://*.loca.lt")
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
elif DEBUG:
    # Локально за trycloudflare / ngrok: браузер — HTTPS, cloudflared — HTTP на :8000.
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    USE_X_FORWARDED_HOST = True
elif os.getenv("DJANGO_USE_TLS_PROXY_HEADERS", "").lower() in ("1", "true", "yes", "on"):
    # Тот же случай при DEBUG=False (часто в .env): без этого POST с https://*.trycloudflare.com
    # на локальный :8000 даёт 403 CSRF / неверный scheme.
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
# Автозаполнение формы входа TikTok в UI настроек: false — только ручной ввод (по умолчанию);
# true — подставлять TIKTOK_USERNAME / TIKTOK_PASSWORD при наличии пары.
TIKTOK_AUTH_AUTOFILL = os.getenv("TIKTOK_AUTH_AUTOFILL", "false")
# SadCaptcha (tiktok-captcha-solver): ключ в worker_accounts.env, не коммитить.
SADCAPTCHA_API_KEY = os.getenv("SADCAPTCHA_API_KEY", "").strip()

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

# Bot API (@BotFather) — отчёт автообновления (не путать с Telethon выше).
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_AUTO_REFRESH_CHAT_ID = os.getenv("TELEGRAM_AUTO_REFRESH_CHAT_ID", "")

# Глобальные границы паузы между аккаунтами в refresh_all / автообновлении (секунды).
# 0,0 — не задавать глобальный clamp (остаются паузы по платформе, см. accounts.views._refresh_all_delay_seconds).
# Для жёсткого ограничения всех платформ: REFRESH_ALL_DELAY_MIN=5 REFRESH_ALL_DELAY_MAX=12.
# Пер-платформа: REFRESH_ALL_DELAY_YOUTUBE_MIN / _MAX и т.д. (имя платформы в env — UPPER).
REFRESH_ALL_DELAY_MIN = float(os.getenv("REFRESH_ALL_DELAY_MIN", "0") or "0")
REFRESH_ALL_DELAY_MAX = float(os.getenv("REFRESH_ALL_DELAY_MAX", "0") or "0")

# ── Apify (альтернатива Playwright для refresh FB / TT / IG) ─────────────────
APIFY_TOKEN = os.getenv("APIFY_TOKEN", "").strip()
APIFY_ENABLED = os.getenv("APIFY_ENABLED", "0").strip().lower() in ("1", "true", "yes", "on")
APIFY_ACTOR_TIKTOK = os.getenv("APIFY_ACTOR_TIKTOK", "clockworks/tiktok-profile-scraper").strip()
APIFY_ACTOR_FACEBOOK_PROFILE = os.getenv(
    "APIFY_ACTOR_FACEBOOK_PROFILE", "crowdpull/facebook-profile-scraper"
).strip()
APIFY_ACTOR_FACEBOOK_PLAYCOUNT = os.getenv(
    "APIFY_ACTOR_FACEBOOK_PLAYCOUNT", "social_developer/facebook-playcount-scraper"
).strip()
APIFY_ACTOR_INSTAGRAM_PROFILE = os.getenv(
    "APIFY_ACTOR_INSTAGRAM_PROFILE", "apify/instagram-profile-scraper"
).strip()
APIFY_ACTOR_INSTAGRAM_POSTS = os.getenv("APIFY_ACTOR_INSTAGRAM_POSTS", "apify/instagram-scraper").strip()
APIFY_MAX_CONCURRENT_RUNS = max(1, int(os.getenv("APIFY_MAX_CONCURRENT_RUNS", "3") or "3"))
APIFY_POLL_INTERVAL_SEC = max(5, int(os.getenv("APIFY_POLL_INTERVAL_SEC", "15") or "15"))
APIFY_POLL_MAX_WAIT_SEC = int(os.getenv("APIFY_POLL_MAX_WAIT_SEC", "0") or "0") or None
APIFY_WEBHOOK_SECRET = os.getenv("APIFY_WEBHOOK_SECRET", "").strip()
APIFY_WEBHOOK_BASE_URL = os.getenv("APIFY_WEBHOOK_BASE_URL", "").strip()
FACEBOOK_MAX_POSTS = max(1, int(os.getenv("FACEBOOK_MAX_POSTS", "80") or "80"))

REST_FRAMEWORK = {
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_AUTHENTICATION_CLASSES": [],
    "DEFAULT_PERMISSION_CLASSES": [],
}
