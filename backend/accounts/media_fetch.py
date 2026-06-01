"""Общая загрузка изображений с CDN (аватары, превью постов)."""

from __future__ import annotations

import logging

import httpx

from .models import Platform

logger = logging.getLogger(__name__)

MEDIA_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

REFERER_BY_PLATFORM = {
    Platform.TIKTOK: "https://www.tiktok.com/",
    Platform.INSTAGRAM: "https://www.instagram.com/",
    Platform.YOUTUBE: "https://www.youtube.com/",
    Platform.TELEGRAM: "https://t.me/",
    Platform.X: "https://x.com/",
    Platform.THREADS: "https://www.threads.com/",
    Platform.FACEBOOK: "https://www.facebook.com/",
    Platform.RUMBLE: "https://rumble.com/",
    Platform.REDDIT: "https://www.reddit.com/",
}


def platform_referer(platform: str) -> str:
    return REFERER_BY_PLATFORM.get(platform, "https://www.google.com/")


def referer_for_image_url(platform: str, url: str) -> str:
    u = (url or "").lower()
    if "cdninstagram.com" in u or "fbcdn.net" in u:
        return "https://www.instagram.com/"
    if "tiktokcdn" in u:
        return "https://www.tiktok.com/"
    if "ytimg.com" in u or "youtube.com" in u:
        return "https://www.youtube.com/"
    if "twimg.com" in u:
        return "https://x.com/"
    return platform_referer(platform)


def ext_from_content_type(content_type: str) -> str:
    ct = (content_type or "").split(";")[0].strip().lower()
    return {
        "image/jpeg": ".jpg",
        "image/jpg": ".jpg",
        "image/png": ".png",
        "image/webp": ".webp",
        "image/gif": ".gif",
        "image/avif": ".avif",
    }.get(ct, ".jpg")


def fetch_image_bytes(url: str, referer: str) -> tuple[bytes, str] | None:
    try:
        r = httpx.get(
            url,
            headers={
                "User-Agent": MEDIA_UA,
                "Referer": referer,
                "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
            },
            follow_redirects=True,
            timeout=10.0,
        )
        if r.status_code == 200 and r.content:
            ct = r.headers.get("content-type", "image/jpeg").split(";")[0]
            return r.content, ct
    except Exception as exc:
        logger.debug("media.fetch_failed url=%s err=%s", (url or "")[:80], exc)
    return None
