from django.contrib import admin
from django.urls import path, include

from .health import healthz

urlpatterns = [
    path("admin/", admin.site.urls),
    path("healthz", healthz),
    path("healthz/", healthz),
    path("api/subscribers/", include("subscribers.urls")),
]
