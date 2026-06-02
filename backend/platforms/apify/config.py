"""Чтение настроек Apify из Django settings и ScrapeBackendConfig."""
from __future__ import annotations

from django.conf import settings

from accounts.models import ScrapeBackendChoice, ScrapeBackendConfig

APIFY_MVP_PLATFORMS = frozenset(
    {"facebook", "tiktok", "instagram", "youtube", "reddit", "rumble"}
)


def apify_enabled() -> bool:
    return bool(getattr(settings, "APIFY_ENABLED", False)) and bool(
        (getattr(settings, "APIFY_TOKEN", "") or "").strip()
    )


def apify_token() -> str:
    return (getattr(settings, "APIFY_TOKEN", "") or "").strip()


def use_apify_for_platform(platform: str) -> bool:
    if not apify_enabled():
        return False
    plat = str(platform or "").strip().lower()
    if plat not in APIFY_MVP_PLATFORMS:
        return False
    cfg = ScrapeBackendConfig.get()
    return cfg.get_backend(plat) == ScrapeBackendChoice.APIFY


def actor_for_stage(platform: str, stage: str) -> str:
    plat = str(platform or "").strip().lower()
    st = str(stage or "").strip().lower()
    if plat == "tiktok":
        return getattr(settings, "APIFY_ACTOR_TIKTOK", "clockworks/tiktok-profile-scraper")
    if plat == "facebook":
        if st == "playcount":
            return getattr(
                settings,
                "APIFY_ACTOR_FACEBOOK_PLAYCOUNT",
                "social_developer/facebook-playcount-scraper",
            )
        return getattr(
            settings,
            "APIFY_ACTOR_FACEBOOK_PROFILE",
            "crowdpull/facebook-profile-scraper",
        )
    if plat == "instagram":
        if st == "posts":
            return getattr(settings, "APIFY_ACTOR_INSTAGRAM_POSTS", "apify/instagram-scraper")
        return getattr(
            settings,
            "APIFY_ACTOR_INSTAGRAM_PROFILE",
            "apify/instagram-profile-scraper",
        )
    if plat == "youtube":
        return getattr(settings, "APIFY_ACTOR_YOUTUBE", "streamers/youtube-scraper")
    if plat == "reddit":
        return getattr(settings, "APIFY_ACTOR_REDDIT", "automation-lab/reddit-scraper")
    if plat == "rumble":
        return getattr(settings, "APIFY_ACTOR_RUMBLE", "thescrapelab/apify-rumble-scraper")
    raise ValueError(f"Нет actor Apify для платформы {platform!r}")


def poll_max_wait_sec(platform: str) -> int:
    env_val = getattr(settings, "APIFY_POLL_MAX_WAIT_SEC", None)
    if env_val:
        return int(env_val)
    plat = str(platform or "").strip().lower()
    if plat == "facebook":
        return 900
    if plat == "tiktok":
        return 300
    if plat == "instagram":
        return 120
    if plat == "youtube":
        return 240
    if plat == "reddit":
        return 180
    if plat == "rumble":
        return 240
    return 600
