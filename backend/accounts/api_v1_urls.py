"""URL-ы внешнего API v1."""
from django.urls import include, path
from rest_framework.routers import DefaultRouter

from accounts.api_v1_views import (
    ExternalAccountViewSet,
    V1DomainListView,
    V1JobDetailView,
    V1SummaryView,
    V1ViewsAnchorsView,
)

router = DefaultRouter()
router.register("accounts", ExternalAccountViewSet, basename="v1-account")

urlpatterns = [
    path("summary/", V1SummaryView.as_view()),
    path("views-anchors/", V1ViewsAnchorsView.as_view()),
    path("domains/", V1DomainListView.as_view()),
    path("jobs/<int:pk>/", V1JobDetailView.as_view()),
    path("", include(router.urls)),
]
