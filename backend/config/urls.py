from django.contrib import admin
from django.urls import path, include
from accounts.settings_views import (
    auth_logout,
    auth_status,
    job_status,
    tiktok_start_auth,
    tiktok_browser_profile,
    tiktok_import_cookies,
    instagram_start_auth,
    instagram_import_cookies,
    telegram_start_auth,
    x_start_auth,
    x_import_cookies,
    threads_start_auth,
    threads_import_cookies,
    facebook_start_auth,
    facebook_browser_profile,
    facebook_import_cookies,
    rumble_start_auth,
    rumble_import_cookies,
    reddit_start_auth,
    reddit_import_cookies,
)
from accounts.views import account_avatar
from .health import healthz, healthz_ready

urlpatterns = [
    # Оба варианта: без завершающего слэша Railway иногда не делает редирект.
    path("healthz", healthz),
    path("healthz/", healthz),
    path("healthz/ready", healthz_ready),
    path("healthz/ready/", healthz_ready),
    path("admin/", admin.site.urls),
    path("api/accounts/", include("accounts.urls")),
    path("api/tiktok/", include("tiktok_app.urls")),
    # Avatar proxy (bypasses CDN expiry / hotlink issues)
    path("api/accounts/<int:pk>/avatar/", account_avatar),
    # Settings / auth management
    path("api/settings/status/", auth_status),
    path("api/settings/<slug:platform>/logout/", auth_logout),
    path("api/settings/job/<str:job_id>/", job_status),
    path("api/settings/tiktok/start-auth/",         tiktok_start_auth),
    path("api/settings/tiktok/browser-profile/",    tiktok_browser_profile),
    path("api/settings/tiktok/import-cookies/",     tiktok_import_cookies),
    path("api/settings/instagram/start-auth/",      instagram_start_auth),
    path("api/settings/instagram/import-cookies/",  instagram_import_cookies),
    path("api/settings/telegram/start-auth/",       telegram_start_auth),
    path("api/settings/x/start-auth/",              x_start_auth),
    path("api/settings/x/import-cookies/",          x_import_cookies),
    path("api/settings/threads/start-auth/",         threads_start_auth),
    path("api/settings/threads/import-cookies/",     threads_import_cookies),
    path("api/settings/facebook/start-auth/",        facebook_start_auth),
    path("api/settings/facebook/browser-profile/",   facebook_browser_profile),
    path("api/settings/facebook/import-cookies/",    facebook_import_cookies),
    path("api/settings/rumble/start-auth/",          rumble_start_auth),
    path("api/settings/rumble/import-cookies/",      rumble_import_cookies),
    path("api/settings/reddit/start-auth/",          reddit_start_auth),
    path("api/settings/reddit/import-cookies/",      reddit_import_cookies),
]
