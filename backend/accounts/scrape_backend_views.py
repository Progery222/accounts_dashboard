"""API настроек backend сбора данных."""
from __future__ import annotations

from django.conf import settings
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response

from accounts.models import ScrapeBackendChoice, ScrapeBackendConfig

from platforms.apify.config import apify_enabled


def _scrape_backend_to_dict(cfg: ScrapeBackendConfig) -> dict:
    return {
        "facebook_backend": cfg.facebook_backend,
        "tiktok_backend": cfg.tiktok_backend,
        "instagram_backend": cfg.instagram_backend,
        "youtube_backend": cfg.youtube_backend,
        "reddit_backend": cfg.reddit_backend,
        "rumble_backend": cfg.rumble_backend,
        "apify_enabled": apify_enabled(),
        "apify_configured": bool((getattr(settings, "APIFY_TOKEN", "") or "").strip()),
    }


@api_view(["GET", "PATCH"])
def scrape_backend(request):
    cfg = ScrapeBackendConfig.get()
    if request.method == "GET":
        data = _scrape_backend_to_dict(cfg)
        from accounts.apify_completion import count_active_apify_jobs

        data["apify_active_jobs"] = count_active_apify_jobs()
        return Response(data)

    data = request.data or {}
    for field in (
        "facebook_backend",
        "tiktok_backend",
        "instagram_backend",
        "youtube_backend",
        "reddit_backend",
        "rumble_backend",
    ):
        if field not in data:
            continue
        val = str(data[field] or "").strip().lower()
        if val not in (ScrapeBackendChoice.PLAYWRIGHT, ScrapeBackendChoice.APIFY):
            return Response(
                {field: "Допустимо: playwright или apify"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if val == ScrapeBackendChoice.APIFY and not apify_enabled():
            return Response(
                {
                    "detail": (
                        "Apify недоступен: задайте APIFY_ENABLED=1 и APIFY_TOKEN в окружении."
                    ),
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        setattr(cfg, field, val)
    cfg.save()
    out = _scrape_backend_to_dict(cfg)
    from accounts.apify_completion import count_active_apify_jobs

    out["apify_active_jobs"] = count_active_apify_jobs()
    return Response(out)
