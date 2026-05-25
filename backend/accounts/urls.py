from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .subs_api import subs_tiktok_audience_bulk
from .views import (
    AccountViewSet, ProfileViewSet, platforms, summary, refresh_schedule,
    auto_refresh_status, auto_refresh_series, auto_refresh_run_now, auto_refresh_stop,
    auto_refresh_reset_state,
    auto_refresh_report_download,
    auto_refresh_last_error_ids,
    refresh_all_status, refresh_all_stop, refresh_all_report_download,
    audience_scrape_stop,
    global_visibility,
)
from .analytics import top_posts, insights

accounts_router = DefaultRouter()
accounts_router.register("", AccountViewSet, basename="account")

profiles_router = DefaultRouter()
profiles_router.register("", ProfileViewSet, basename="profile")

urlpatterns = [
    path("platforms/", platforms),
    path("summary/", summary),
    path("visibility/", global_visibility),
    path("schedule/", refresh_schedule),
    path("auto-refresh-status/", auto_refresh_status),
    path("auto-refresh-series/", auto_refresh_series),
    path("auto-refresh-run-now/", auto_refresh_run_now),
    path("auto-refresh-stop/", auto_refresh_stop),
    path("auto-refresh-reset-state/", auto_refresh_reset_state),
    path("auto-refresh-report/", auto_refresh_report_download),
    path("auto-refresh-last-error-ids/", auto_refresh_last_error_ids),
    path("refresh-all-status/", refresh_all_status),
    path("refresh-all-stop/", refresh_all_stop),
    path("audience-scrape-stop/", audience_scrape_stop),
    path("subs/tiktok-audience/bulk/", subs_tiktok_audience_bulk),
    path("refresh-all-report/", refresh_all_report_download),
    path("analytics/top-posts/", top_posts),
    path("analytics/insights/", insights),
    path("profiles/", include(profiles_router.urls)),
    path("", include(accounts_router.urls)),
]
