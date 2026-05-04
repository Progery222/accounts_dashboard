from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import AccountViewSet, ProfileViewSet, platforms, summary, refresh_schedule
from .analytics import top_posts, insights

accounts_router = DefaultRouter()
accounts_router.register("", AccountViewSet, basename="account")

profiles_router = DefaultRouter()
profiles_router.register("", ProfileViewSet, basename="profile")

urlpatterns = [
    path("platforms/", platforms),
    path("summary/", summary),
    path("schedule/", refresh_schedule),
    path("analytics/top-posts/", top_posts),
    path("analytics/insights/", insights),
    path("profiles/", include(profiles_router.urls)),
    path("", include(accounts_router.urls)),
]
