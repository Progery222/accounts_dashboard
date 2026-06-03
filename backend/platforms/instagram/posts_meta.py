"""Лимиты постов IG (Playwright/Instaloader) и флаг authoritative для sync в БД."""
from __future__ import annotations

import os


def instagram_max_posts() -> int:
    """Согласовано с Apify resultsLimit (по умолчанию 80)."""
    raw = os.environ.get("INSTAGRAM_MAX_POSTS")
    if raw is None or not str(raw).strip():
        try:
            from django.conf import settings

            raw = getattr(settings, "INSTAGRAM_MAX_POSTS", 80)
        except Exception:
            raw = 80
    try:
        return max(12, min(200, int(raw or 80)))
    except (TypeError, ValueError):
        return 80


def instagram_reels_scroll_iterations() -> int:
    """Скроллы вкладки /reels/ — больше постов при большем лимите."""
    cap = instagram_max_posts()
    return max(16, min(40, (cap + 7) // 5))


def annotate_instagram_posts_payload(payload: dict) -> dict:
    """
    Если собрали заметно меньше постов, чем post_count в профиле — не authoritative:
    _sync_posts не помечает «пропавшие» посты удалёнными (как у Apify _partial).
    """
    if not isinstance(payload, dict):
        return payload
    if "_posts" not in payload:
        return payload
    posts = list(payload.get("_posts") or [])
    post_count = int(payload.get("post_count") or 0)
    n = len(posts)
    if post_count > 0:
        authoritative = n >= max(1, int(post_count * 0.8))
    else:
        authoritative = True
    payload["_posts_authoritative"] = authoritative
    if post_count > n and post_count > instagram_max_posts():
        payload["_partial"] = True
    elif post_count > 0 and not authoritative:
        payload["_partial"] = True
    return payload
