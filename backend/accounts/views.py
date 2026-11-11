import datetime
import logging
import os
import random
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import httpx
import io
import csv
from django.conf import settings
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from django.db.models import (
    Sum,
    Q,
    Count,
    F,
    OuterRef,
    Subquery,
    IntegerField,
    BigIntegerField,
    Case,
    When,
    Value,
)
from django.db.models.functions import Coalesce
from django.db import transaction
from django.db.utils import InterfaceError, OperationalError, ProgrammingError
from rest_framework import viewsets, status
from rest_framework.decorators import api_view, action
from rest_framework.parsers import JSONParser, MultiPartParser
from rest_framework.response import Response
from .constants import NEW_ACCOUNT_UPDATED_AT
from . import domains
from .models import (
    Account,
    Domain,
    Platform,
    Post,
    Profile,
    Owner,
    AccountGroup,
    Country,
    AccountSnapshot,
    PostSnapshot,
    AutoRefreshPoint,
    AutoRefreshState,
    GlobalVisibilityConfig,
    RefreshAllState,
    RefreshScheduleConfig,
)
from .serializers import (
    AccountSerializer,
    PostSerializer,
    ProfileSerializer,
    OwnerSerializer,
    AccountGroupSerializer,
    CountrySerializer,
)
from .snapshot_io import build_snapshot_csv, import_snapshot_csv, _is_deadlock_error
from platforms.profile_unavailable import (
    is_profile_unavailable_error,
    user_visible_profile_unavailable_error,
)

logger = logging.getLogger(__name__)


def _is_refresh_stats_rejection(exc: BaseException) -> bool:
    """╨Ю╤В╨║╨░╨╖ ╤Б╨╛╤Е╤А╨░╨╜╨╕╤В╤М ╨┐╨╛╨┤╨╛╨╖╤А╨╕╤В╨╡╨╗╤М╨╜╤Л╨╡ ╨╜╤Г╨╗╨╕ тАФ ╨╜╨╡ ╨┐╤Г╤В╨░╤В╤М ╤Б ╤Г╨┤╨░╨╗╤С╨╜╨╜╤Л╨╝ ╨┐╤А╨╛╤Д╨╕╨╗╨╡╨╝ ╨╜╨░ ╨┐╨╗╨╛╤Й╨░╨┤╨║╨╡."""
    return "╨Ю╨▒╨╜╨╛╨▓╨╗╨╡╨╜╨╕╨╡ ╨╜╨╡ ╨┐╤А╨╕╨╝╨╡╨╜╨╡╨╜╨╛" in str(exc or "")


def _mark_profile_unavailable_if_applicable(account: Account, exc: BaseException) -> None:
    if _is_refresh_stats_rejection(exc):
        return
    if getattr(account, "platform", None) == Platform.FACEBOOK:
        try:
            from platforms.facebook.rate_limit import is_facebook_rate_limited_error

            if is_facebook_rate_limited_error(exc):
                return
        except Exception:
            pass
    if not is_profile_unavailable_error(str(exc)):
        return
    Account.objects.filter(pk=account.pk).update(profile_unavailable=True)
    account.profile_unavailable = True

# Serialize refreshes per account id so concurrent POST /refresh/ waits instead of 409.
_REGISTRY_LOCK = threading.Lock()
_ACCOUNT_REFRESH_MUTEXES: dict[int, threading.Lock] = {}


def _account_refresh_mutex(account_id: int) -> threading.Lock:
    with _REGISTRY_LOCK:
        lock = _ACCOUNT_REFRESH_MUTEXES.get(account_id)
        if lock is None:
            lock = threading.Lock()
            _ACCOUNT_REFRESH_MUTEXES[account_id] = lock
        return lock


def _extract_hashtags(text: str) -> list[str]:
    """Return a sorted, deduplicated list of lowercase hashtags found in text."""
    return sorted(set(tag.lower() for tag in re.findall(r"#([\w\u0400-\u04FF]+)", text)))


def _account_delta_period_days() -> int:
    """╨Ф╨╡╨╗╤М╤В╤Л ╨░╨║╨║╨░╤Г╨╜╤В╨╛╨▓: ╨╛╨┐╨╛╤А╨╜╤Л╨╣ ╤Б╨╜╨╕╨╝╨╛╨║ тАФ ╨┐╨╛╤Б╨╗╨╡╨┤╨╜╨╕╨╣ ╤Б ╨┤╨░╤В╨╛╨╣ тЙд ╤Б╨╡╨│╨╛╨┤╨╜╤П тИТ N ╨┤╨╜╨╡╨╣ (1, 7 ╨╕╨╗╨╕ 30)."""
    try:
        cfg = RefreshScheduleConfig.get()
        d = int(getattr(cfg, "account_delta_period_days", 1) or 1)
    except Exception:
        return 1
    return d if d in (1, 7, 30) else 1


def _effective_account_delta_period_days(request) -> int:
    """
    ╨Ф╨╗╤П GET: ╨╝╨╛╨╢╨╜╨╛ ╨┐╨╡╤А╨╡╨┤╨░╤В╤М delta_period_days=1|7|30 тАФ ╨╜╨╡ ╨┐╨╕╤И╨╡╤В ╨▓ ╨С╨Ф, ╤Г╨┤╨╛╨▒╨╜╨╛ ╨┤╨╗╤П ╨┐╤А╨╡╤Д╨╡╤В╤З╨░ UI.
    ╨Ф╨╗╤П ╨╛╤Б╤В╨░╨╗╤М╨╜╤Л╤Е ╨╝╨╡╤В╨╛╨┤╨╛╨▓ ╨╕ ╨┐╤А╨╕ ╨╛╤В╤Б╤Г╤В╤Б╤В╨▓╨╕╨╕/╨╜╨╡╨▓╨░╨╗╨╕╨┤╨╜╨╛╨╝ ╨┐╨░╤А╨░╨╝╨╡╤В╤А╨╡ тАФ ╨╖╨╜╨░╤З╨╡╨╜╨╕╨╡ ╨╕╨╖ RefreshScheduleConfig.
    """
    if getattr(request, "method", "") != "GET":
        return _account_delta_period_days()
    raw = request.query_params.get("delta_period_days")
    if raw is None or str(raw).strip() == "":
        return _account_delta_period_days()
    try:
        v = int(raw)
    except (TypeError, ValueError):
        return _account_delta_period_days()
    return v if v in (1, 7, 30) else _account_delta_period_days()


def _scrape(account: Account) -> dict:
    """Fetch fresh data for any platform. Returns account fields + '_posts' list."""
    from .refresh_cancel import RefreshCancelledError, raise_if_refresh_cancel_requested

    # ╨Э╨╡ ╨┤╨╡╤А╨╢╨╕╨╝ ╤Б╨╛╨╡╨┤╨╕╨╜╨╡╨╜╨╕╨╡ ╤Б ╨С╨Ф ╨╛╤В╨║╤А╤Л╤В╤Л╨╝ ╨▓╨╛ ╨▓╤А╨╡╨╝╤П Playwright/HTTP (╨╝╨╕╨╜╤Г╤В╤Л).
    release_db_for_long_task()
    raise_if_refresh_cancel_requested()
    username = account.username
    platform = account.platform

    from platforms.apify.config import use_apify_for_platform

    if use_apify_for_platform(platform):
        raise ValueError(
            f"╨Ф╨╗╤П {platform} ╨▓ ╨╜╨░╤Б╤В╤А╨╛╨╣╨║╨░╤Е ╨▓╤Л╨▒╤А╨░╨╜ Apify тАФ ╨╕╤Б╨┐╨╛╨╗╤М╨╖╤Г╨╣╤В╨╡ ╤Б╨▒╨╛╤А ╤З╨╡╤А╨╡╨╖ Apify, "
            "╨░ ╨╜╨╡ Playwright/HTTP"
        )

    if platform == Platform.TIKTOK:
        from platforms.tiktok.service import fetch_tiktok_profile
        raw = fetch_tiktok_profile(username)
        posts = [
            {
                "external_id": str(v["id"]),
                "description": v.get("description", ""),
                "thumbnail_url": v.get("cover", ""),
                "post_url": f"https://www.tiktok.com/@{username}/video/{v['id']}",
                "view_count": v.get("play_count", 0),
                "like_count": v.get("like_count", 0),
                "comment_count": v.get("comment_count", 0),
                "share_count": v.get("share_count", 0),
                "posted_at": (
                    datetime.datetime.fromtimestamp(v["created_at"], tz=datetime.timezone.utc)
                    if v.get("created_at") else None
                ),
            }
            for v in raw.get("videos", [])
        ]
        result = {
            "display_name": raw["nickname"],
            "avatar_url": raw.get("avatar") or None,
            "bio": raw["bio"],
            "follower_count": raw["follower_count"],

            "like_count": raw["like_count"],
            "post_count": raw["video_count"],
            "_posts": posts,
            # ╨Я╤А╨╛╨▒╤А╨░╤Б╤Л╨▓╨░╨╡╨╝ ╤Д╨╗╨░╨│ ╨░╨▓╤В╨╛╤А╨╕╤В╨╡╤В╨╜╨╛╤Б╤В╨╕ ╤Б╨┐╨╕╤Б╨║╨░ ╨┐╨╛╤Б╤В╨╛╨▓ ╨╕╨╖ service.py.
            # ╨Ф╨╗╤П TikTok ╨┐╤Г╤Б╤В╨╛╨╣ `videos` ╨┐╨╛╤З╤В╨╕ ╨▓╤Б╨╡╨│╨┤╨░ тАФ ╨░╨╜╤В╨╕╨▒╨╛╤В/╨▓╤А╨╡╨╝╨╡╨╜╨╜╨░╤П ╨▒╨╗╨╛╨║╨╕╤А╨╛╨▓╨║╨░
            # API, ╨░ ╨╜╨╡ ╤А╨╡╨░╨╗╤М╨╜╨╛╨╡ ╤Г╨┤╨░╨╗╨╡╨╜╨╕╨╡ ╨▓╤Б╨╡╤Е ╨┐╨╛╤Б╤В╨╛╨▓ ╨┐╤А╨╛╤Д╨╕╨╗╤П. ╨Т ╤Н╤В╨╛╨╝ ╤Б╨╗╤Г╤З╨░╨╡
            # service.py ╨▓╤Л╤Б╤В╨░╨▓╨╗╤П╨╡╤В _posts_authoritative=False, ╨╕ _apply_refresh
            # ╤Б╨╛╤Е╤А╨░╨╜╤П╨╡╤В ╤Г╨╢╨╡ ╤Б╨╛╤Е╤А╨░╨╜╤С╨╜╨╜╤Л╨╡ ╨▓ ╨С╨Ф ╨┐╨╛╤Б╤В╤Л ╨▓╨╝╨╡╤Б╤В╨╛ ╨╕╤Е ╤Г╨┤╨░╨╗╨╡╨╜╨╕╤П.
            "_posts_authoritative": raw.get("_posts_authoritative", bool(posts)),
        }
        if raw.get("_partial"):
            result["_partial"] = True
        return result

    if platform == Platform.TELEGRAM:
        from platforms.telegram.scraper import fetch_telegram_profile
        return fetch_telegram_profile(username)

    if platform == Platform.YOUTUBE:
        from platforms.youtube.scraper import fetch_youtube_channel
        return fetch_youtube_channel(username)

    if platform == Platform.INSTAGRAM:
        from platforms.instagram.scraper import fetch_instagram_profile
        return fetch_instagram_profile(username)

    if platform == Platform.X:
        from platforms.x.scraper import fetch_x_profile
        return fetch_x_profile(username)

    if platform == Platform.THREADS:
        from platforms.threads.scraper import fetch_threads_profile
        return fetch_threads_profile(username)

    if platform == Platform.FACEBOOK:
        from platforms.facebook.scraper import fetch_facebook_profile
        return fetch_facebook_profile(username)

    if platform == Platform.RUMBLE:
        from platforms.rumble.scraper import fetch_rumble_profile
        return fetch_rumble_profile(username)

    if platform == Platform.REDDIT:
        from platforms.reddit.scraper import fetch_reddit_subreddit
        return fetch_reddit_subreddit(username)

    raise ValueError(f"╨Ю╨▒╨╜╨╛╨▓╨╗╨╡╨╜╨╕╨╡ ╨┤╨╗╤П ┬л{platform}┬╗ ╨╜╨╡ ╨┐╨╛╨┤╨┤╨╡╤А╨╢╨╕╨▓╨░╨╡╤В╤Б╤П.")


def _mark_unseen_posts_missing(account: Account, seen_external_ids: set[str]) -> None:
    """╨Я╨╛╨╝╨╡╤В╨╕╤В╤М ╨┐╨╛╤Б╤В╤Л, ╨╛╤В╤Б╤Г╤В╤Б╤В╨▓╤Г╤О╤Й╨╕╨╡ ╨▓ ╤Г╤Б╨┐╨╡╤И╨╜╨╛╨╝ ╤Б╤К╤С╨╝╨╡ (╨╛╤А╨░╨╜╨╢╨╡╨▓╨░╤П ╨╗╨░╨╝╨┐╨╛╤З╨║╨░ ╨▓ UI)."""
    now = timezone.now()
    account.posts.exclude(external_id__in=seen_external_ids).filter(
        missing_from_scrape_at__isnull=True,
    ).update(missing_from_scrape_at=now)


def _sync_posts(
    account: Account,
    posts_data: list,
    *,
    mark_unseen_missing: bool = True,
) -> set[str]:
    today = timezone.localdate()
    seen_external_ids: set[str] = set()
    is_instagram = account.platform == Platform.INSTAGRAM
    is_threads = account.platform == Platform.THREADS
    is_facebook = account.platform == Platform.FACEBOOK
    is_rumble = account.platform == Platform.RUMBLE

    def _to_int(v) -> int:
        if v is None:
            return 0
        if isinstance(v, (int, float)):
            return int(v)
        s = str(v).strip().replace("\u00a0", "").replace("\u202f", "").replace(" ", "")
        if not s:
            return 0
        # Preserve digits only for resilient parsing ("1,234", "1.2K" -> "12" won't be ideal,
        # but most platform workers already normalize; this is just a safety net).
        digits = re.sub(r"[^\d]", "", s)
        return int(digits) if digits else 0

    for pd in posts_data:
        external_id = str(pd.get("external_id") or "").strip()
        if not external_id:
            continue
        seen_external_ids.add(external_id)
        post, _ = Post.objects.get_or_create(
            account=account,
            external_id=external_id,
        )
        # Ensure today's snapshot exists before updating
        post.take_snapshot_if_needed()
        scrape_included_thumbnail = "thumbnail_url" in pd
        scraped_thumbnail_url = pd.get("thumbnail_url") if scrape_included_thumbnail else None
        # Update content fields
        for field in ("description", "thumbnail_url", "post_url", "posted_at"):
            if field in pd and pd[field] is not None:
                if field == "thumbnail_url" and isinstance(pd[field], str) and not pd[field].strip():
                    continue
                setattr(post, field, pd[field])
        # Update numeric fields with resilient coercion + fallback aliases
        parsed_views = _to_int(pd.get("view_count", pd.get("play_count", 0)))
        # Threads / Instagram: 0 ╤Б╨╛ ╤Б╨║╤А╨░╨┐╨░ ╤З╨░╤Б╤В╨╛ ┬л╨╜╨╡╤В ╨▓ DOM / ╨╜╨╡ ╤Г╤Б╨┐╨╡╨╗╨╕┬╗, ╨░ ╨╜╨╡ ╤А╨╡╨░╨╗╤М╨╜╤Л╨╡ 0 ╨┐╤А╨╛╤Б╨╝╨╛╤В╤А╨╛╨▓.
        # ╨Э╨╡ ╨╖╨░╤В╨╕╤А╨░╨╡╨╝ ╤Б╨╛╤Е╤А╨░╨╜╤С╨╜╨╜╤Л╨╡ ╨╖╨╜╨░╤З╨╡╨╜╨╕╤П тАФ ╨╕╨╜╨░╤З╨╡ ╤Б╤Г╨╝╨╝╨░ ╨┐╨╛ ╨┐╨╛╤Б╤В╨░╨╝ ╨╕ ╨┤╨╡╨╗╤М╤В╤Л ╨▓ UI ╨┐╨░╨┤╨░╤О╤В ╨▓ ╨╝╨╕╨╜╤Г╤Б.
        if is_threads or is_instagram or is_rumble:
            if parsed_views > 0:
                prev_v = int(post.view_count or 0)
                post.view_count = max(prev_v, parsed_views)
            # parsed_views == 0 тАФ ╨╜╨╡ ╤В╤А╨╛╨│╨░╨╡╨╝ post.view_count
        else:
            post.view_count = parsed_views
        parsed_like_count = _to_int(pd.get("like_count", pd.get("digg_count", 0)))
        # Instagram: 0 ╤Б╨╛ ╤Б╨║╤А╨░╨┐╨░ = ┬л╨┤╨░╨╜╨╜╤Л╤Е ╨╜╨╡╤В┬╗, ╨╜╨╡ ╤Г╨╝╨╡╨╜╤М╤И╨░╨╡╨╝ ╤Б╨╛╤Е╤А╨░╨╜╤С╨╜╨╜╤Л╨╡ ╨╗╨░╨╣╨║╨╕.
        # ╨Я╨╛╨╗╨╛╨╢╨╕╤В╨╡╨╗╤М╨╜╨╛╨╡ ╨╖╨╜╨░╤З╨╡╨╜╨╕╨╡ ╤Б╤З╨╕╤В╨░╨╡╨╝ ╨▓╨░╨╗╨╕╨┤╨╜╤Л╨╝ ╨╕ ╨┐╤А╨╕╨╝╨╡╨╜╤П╨╡╨╝ ╤В╨╛╨╗╤М╨║╨╛ ╨╜╨╡ ╨╜╨╕╨╢╨╡ ╤Г╨╢╨╡ ╤Б╨╛╤Е╤А╨░╨╜╤С╨╜╨╜╨╛╨│╨╛.
        if is_instagram:
            if parsed_like_count > 0:
                prev_likes = int(post.like_count or 0)
                post.like_count = max(prev_likes, parsed_like_count)
        # Facebook: 0 ╨▒╨╡╨╖ ╨┐╨╛╨┤╤В╨▓╨╡╤А╨╢╨┤╨╡╨╜╨╕╤П тАФ ┬л╨┤╨░╨╜╨╜╤Л╤Е ╨╜╨╡╤В┬╗; confirmed ╨┐╨╛╤Б╨╗╨╡ detail (╨║╨╜╨╛╨┐╨║╨░ ╨▓ viewport) тАФ ╨┐╨╕╤И╨╡╨╝ 0.
        elif is_facebook:
            if pd.get("like_count_confirmed"):
                post.like_count = parsed_like_count
            elif parsed_like_count > 0:
                prev_likes = int(post.like_count or 0)
                post.like_count = max(prev_likes, parsed_like_count)
        else:
            post.like_count = parsed_like_count
        post.comment_count = _to_int(pd.get("comment_count", 0))
        post.share_count = _to_int(pd.get("share_count", 0))
        # Extract and store hashtags from description
        post.hashtags = _extract_hashtags(post.description)
        post.save()
        from .post_thumbnail_storage import ensure_post_thumbnail_after_sync

        post.refresh_from_db(fields=["thumbnail_url", "thumbnail_file", "thumbnail_missing"])
        ensure_post_thumbnail_after_sync(
            post,
            account,
            scrape_included_thumbnail=scrape_included_thumbnail,
            scraped_thumbnail_url=scraped_thumbnail_url,
        )
        # Keep today's post snapshot current тАФ correct baseline for tomorrow's delta.
        # Also fixes zero snapshots left over from before the first real scrape.
        post.snapshots.filter(date=today).update(
            view_count=post.view_count,
            like_count=post.like_count,
            comment_count=post.comment_count,
        )
        post.snapshots.filter(date__lt=today, view_count=0, like_count=0, comment_count=0).update(
            view_count=post.view_count,
            like_count=post.like_count,
            comment_count=post.comment_count,
        )

    if seen_external_ids:
        # ╨Я╨╛╤Б╤В ╤Б╨╜╨╛╨▓╨░ ╨▓ ╤Б╤К╤С╨╝╨╡ тАФ ╤Б╨╜╨╕╨╝╨░╨╡╨╝ ┬л╨╜╨╡ ╨╜╨░╨╣╨┤╨╡╨╜┬╗ (╨╗╨░╨╝╨┐╨╛╤З╨║╨░ ╨▓ UI ╨┐╤А╨╛╨┐╨░╨┤╨░╨╡╤В).
        account.posts.filter(external_id__in=seen_external_ids).update(
            missing_from_scrape_at=None,
        )
    if mark_unseen_missing:
        _mark_unseen_posts_missing(account, seen_external_ids)
    return seen_external_ids


def _posts_for_account_stats(account: Account):
    """╨Я╨╛╤Б╤В╤Л, ╤Г╤З╨░╤Б╤В╨▓╤Г╤О╤Й╨╕╨╡ ╨▓ ╤Б╤Г╨╝╨╝╨░╤Е ╨┐╤А╨╛╤Б╨╝╨╛╤В╤А╨╛╨▓/╨╗╨░╨╣╨║╨╛╨▓ ╨╕ ╨▓ ╤Б╤З╤С╤В╤З╨╕╨║╨╡ ╨┐╤Г╨▒╨╗╨╕╨║╨░╤Ж╨╕╨╣."""
    return account.posts.filter(missing_from_scrape_at__isnull=True)


def _apply_post_aggregates_to_account(account: Account, stats_before: dict) -> None:
    """
    ╨Я╨╡╤А╨╡╤Б╤З╤С╤В view_count / like_count / post_count ╨┐╨╛ ╨┐╨╛╤Б╤В╨░╨╝ ╨▒╨╡╨╖ ┬л╨╜╨╡ ╨╜╨░╨╣╨┤╨╡╨╜ ╨┐╤А╨╕ ╤Б╨║╤А╨░╨┐╨╡┬╗.
    ╨Ш╤В╨╛╨│╨╛╨▓╤Л╨╡ ╨╖╨╜╨░╤З╨╡╨╜╨╕╤П ╨╜╨╡ ╤Г╨╝╨╡╨╜╤М╤И╨░╨╡╨╝ ╨╛╤В╨╜╨╛╤Б╨╕╤В╨╡╨╗╤М╨╜╨╛ stats_before (╨┐╨╛╨╝╨╡╤З╨╡╨╜╨╜╤Л╨╡ ╨┐╨╛╤Б╤В╤Л ╨╜╨╡ ┬л╤А╨╛╨╜╤П╤О╤В┬╗ ╨╝╨╡╤В╤А╨╕╨║╨╕).
    """
    agg = _posts_for_account_stats(account).aggregate(
        total_views=Sum("view_count"),
        total_likes=Sum("like_count"),
    )
    new_views = int(agg["total_views"] or 0)
    prev_views = int(stats_before.get("view_count", 0) or 0)
    if account.platform == Platform.FACEBOOK:
        account.view_count = max(prev_views, new_views)
    elif account.platform in (Platform.RUMBLE, Platform.YOUTUBE):
        # YouTube/Rumble: ╨▓ ╤И╨░╨┐╨║╨╡ ╨║╨░╨╜╨░╨╗╨░ ╨╡╤Б╤В╤М ╨┐╨╛╨╗╨╜╤Л╨╣ viewCount; ╤Б╤Г╨╝╨╝╨░ ╨┐╨╛╤Б╨╗╨╡╨┤╨╜╨╕╤Е
        # ╨┐╨╛╤Б╤В╨╛╨▓ ╨╕╨╖ RSS/╨┐╨╗╨╡╨╣╨╗╨╕╤Б╤В╨░ ╨╡╨│╨╛ ╨╖╨░╨╜╨╕╨╢╨░╨╡╤В тАФ ╨▒╨╡╤А╤С╨╝ ╨╝╨░╨║╤Б╨╕╨╝╤Г╨╝ ╨╕╨╖ ╤В╤А╤С╤Е.
        scraped_views = int(account.view_count or 0)
        account.view_count = max(prev_views, new_views, scraped_views)
    elif account.platform in (Platform.INSTAGRAM, Platform.THREADS):
        account.view_count = max(prev_views, new_views)
    else:
        account.view_count = max(prev_views, new_views)
    if account.platform in (
        Platform.YOUTUBE,
        Platform.TELEGRAM,
        Platform.INSTAGRAM,
        Platform.X,
        Platform.THREADS,
        Platform.RUMBLE,
        Platform.REDDIT,
        Platform.FACEBOOK,
    ):
        prev_likes = int(stats_before.get("like_count", 0) or 0)
        account.like_count = max(prev_likes, int(agg["total_likes"] or 0))
    active_post_count = _posts_for_account_stats(account).count()
    prev_post_count = int(stats_before.get("post_count", 0) or 0)
    scraped_post_count = int(account.post_count or 0)
    if account.platform == Platform.TIKTOK:
        if active_post_count == 0:
            # ╨Э╨╡╤В ╨┐╨╛╤Б╤В╨╛╨▓ ╨▓ ╨С╨Ф тАФ ╨╜╨╡ ╨┤╨╡╤А╨╢╨╕╨╝ ╤Г╤Б╤В╨░╤А╨╡╨▓╤И╨╕╨╣ videoCount ╨╕╨╖ ╤И╨░╨┐╨║╨╕.
            account.post_count = 0
        else:
            if scraped_post_count > active_post_count:
                scraped_post_count = active_post_count
            account.post_count = max(prev_post_count, active_post_count, scraped_post_count)
    else:
        account.post_count = max(prev_post_count, active_post_count, scraped_post_count)


_STAT_FIELDS = frozenset(
    ("follower_count", "like_count", "view_count", "post_count")
)
#: ╨Я╨╛╨║╨░╨╖╨░╤В╨╡╨╗╨╕, ╨║╨╛╤В╨╛╤А╤Л╨╡ ╤Б╤З╨╕╤В╨░╤О╤В╤Б╤П ╨┐╨╛ ╤Б╨┐╨╕╤Б╨║╤Г ╨┐╨╛╤Б╤В╨╛╨▓. ╨в╨╛╨╗╤М╨║╨╛ ╨╕╤Е ╨╕╨╝╨╡╨╡╤В ╤Б╨╝╤Л╤Б╨╗
#: ╨┐╤А╨╕╨┤╨╡╤А╨╢╨░╤В╤М, ╨║╨╛╨│╨┤╨░ ╤Б╨┐╨╕╤Б╨╛╨║ ╤Б╨╛╨▒╤А╨░╨╗╤Б╤П ╨╜╨╡ ╤Ж╨╡╨╗╨╕╨║╨╛╨╝. ╨Я╨╛╨┤╨┐╨╕╤Б╤З╨╕╨║╨╕ ╨╕╨╖ ╨┐╨╛╤Б╤В╨╛╨▓ ╨╜╨╡
#: ╨▓╤Л╨▓╨╛╨┤╤П╤В╤Б╤П ╨▓╨╛╨╛╨▒╤Й╨╡ тАФ ╨╛╨╜╨╕ ╨▒╨╡╤А╤Г╤В╤Б╤П ╤Б╨╛ ╤Б╤В╤А╨░╨╜╨╕╤Ж╤Л ╨┐╤А╨╛╤Д╨╕╨╗╤П.
_POST_DERIVED_STAT_FIELDS = frozenset(("like_count", "view_count", "post_count"))

_ACCOUNT_REFRESH_SAVE_FIELDS = (
    "display_name",
    "avatar_url",
    "bio",
    "follower_count",
    "like_count",
    "view_count",
    "post_count",
    "link_click_count",
    "profile_unavailable",
    "updated_at",
)
_ACCOUNT_ASSIGNMENT_FIELDS = frozenset({
    # ╨б╨╝╨╡╨╜╨░ ╨┤╨╛╨╝╨╡╨╜╨░ тАФ ╤В╨░╨║╨╛╨╡ ╨╢╨╡ ╨╜╨░╨╖╨╜╨░╤З╨╡╨╜╨╕╨╡, ╨║╨░╨║ ╨┐╤А╨╛╤Д╨╕╨╗╤М: ┬л╨Ю╨▒╨╜╨╛╨▓╨╗╤С╨╜┬╗ ╨╛╨╜╨░ ╨┤╨▓╨╕╨│╨░╤В╤М
    # ╨╜╨╡ ╨┤╨╛╨╗╨╢╨╜╨░, ╤Н╤В╨╛ ╨╜╨╡ ╤Б╨▒╨╛╤А ╤Б╤В╨░╤В╨╕╤Б╤В╨╕╨║╨╕.
    "domain", "profile", "owner", "group", "country", "profile_unavailable",
    "is_archived", "is_banned",
})


def _account_assignment_only_validated(validated_data: dict) -> bool:
    if not validated_data:
        return False
    return set(validated_data.keys()).issubset(_ACCOUNT_ASSIGNMENT_FIELDS)


def _account_assignment_update_fields(validated_data: dict) -> list[str]:
    """╨Ш╨╝╨╡╨╜╨░ ╨║╨╛╨╗╨╛╨╜╨╛╨║ ╨┤╨╗╤П update_fields (FK тАФ *_id, ╨╜╨╡ source-╨╕╨╝╨╡╨╜╨░ serializer)."""
    out: list[str] = []
    if "domain" in validated_data:
        out.append("domain_id")
    if "profile" in validated_data:
        out.append("profile_id")
    if "owner" in validated_data:
        out.append("owner_id")
    if "group" in validated_data:
        out.append("group_id")
    if "country" in validated_data:
        out.append("country_id")
    if "profile_unavailable" in validated_data:
        out.append("profile_unavailable")
    if "is_archived" in validated_data:
        out.append("is_archived")
    if "is_banned" in validated_data:
        out.append("is_banned")
    return out


def _assignment_fk_id(obj) -> int | None:
    return obj.pk if obj else None


def _existing_account_assignment_unchanged(existing: Account, validated: dict) -> bool:
    """╨б╨╛╨▓╨┐╨░╨┤╨░╤О╤В ╨╗╨╕ ╨┐╨╡╤А╨╡╨┤╨░╨╜╨╜╤Л╨╡ ╨▓ POST ╨┐╨╛╨╗╤П ╨┤╨╛╨╝╨╡╨╜╨░/╨┐╤А╨╛╤Д╨╕╨╗╤П/╨▓╨╗╨░╨┤╨╡╨╗╤М╤Ж╨░/╨│╤А╤Г╨┐╨┐╤Л/╤Б╤В╤А╨░╨╜╤Л ╤Б ╨░╨║╨║╨░╤Г╨╜╤В╨╛╨╝."""
    for key, fk_attr in (
        ("domain", "domain_id"),
        ("profile", "profile_id"),
        ("owner", "owner_id"),
        ("group", "group_id"),
        ("country", "country_id"),
    ):
        if key not in validated:
            continue
        if getattr(existing, fk_attr) != _assignment_fk_id(validated.get(key)):
            return False
    return True


def _unarchive_account_on_import(account: Account) -> bool:
    """╨Я╨╛╨▓╤В╨╛╤А╨╜╤Л╨╣ ╨╕╨╝╨┐╨╛╤А╤В/╨┤╨╛╨▒╨░╨▓╨╗╨╡╨╜╨╕╨╡ ╨▓╨╛╨╖╨▓╤А╨░╤Й╨░╨╡╤В ╨░╨║╨║╨░╤Г╨╜╤В ╨▓ ╨░╨║╤В╤Г╨░╨╗╤М╨╜╤Л╨╡ ╨▒╨╡╨╖ ╤Б╨┤╨▓╨╕╨│╨░ ┬л╨Ю╨▒╨╜╨╛╨▓╨╗╤С╨╜┬╗."""
    if not account.is_archived:
        return False
    preserved = account.updated_at
    Account.objects.filter(pk=account.pk).update(is_archived=False)
    account.is_archived = False
    _restore_account_updated_at(account.pk, preserved)
    return True


def _unban_account_on_import(account: Account) -> bool:
    """╨Я╨╛╨▓╤В╨╛╤А╨╜╤Л╨╣ ╨╕╨╝╨┐╨╛╤А╤В/╨┤╨╛╨▒╨░╨▓╨╗╨╡╨╜╨╕╨╡ ╤Б╨╜╨╕╨╝╨░╨╡╤В ╨▒╨░╨╜ ╨▒╨╡╨╖ ╤Б╨┤╨▓╨╕╨│╨░ ┬л╨Ю╨▒╨╜╨╛╨▓╨╗╤С╨╜┬╗."""
    if not account.is_banned:
        return False
    preserved = account.updated_at
    Account.objects.filter(pk=account.pk).update(is_banned=False)
    account.is_banned = False
    _restore_account_updated_at(account.pk, preserved)
    return True


def _apply_existing_account_assignment(existing: Account, validated: dict) -> list[str]:
    """
    ╨в╨╛╨╗╤М╨║╨╛ ╤Б╨╝╨╡╨╜╨░ ╨┤╨╛╨╝╨╡╨╜╨░/╨┐╤А╨╛╤Д╨╕╨╗╤П/╨▓╨╗╨░╨┤╨╡╨╗╤М╤Ж╨░/╨│╤А╤Г╨┐╨┐╤Л/╤Б╤В╤А╨░╨╜╤Л тАФ ╨▒╨╡╨╖ scrape ╨╕ ╨▒╨╡╨╖ ╤Б╨┤╨▓╨╕╨│╨░ ┬л╨Ю╨▒╨╜╨╛╨▓╨╗╤С╨╜┬╗.
    ╨Т╨╛╨╖╨▓╤А╨░╤Й╨░╨╡╤В ╤Б╨┐╨╕╤Б╨╛╨║ ╨╕╨╖╨╝╨╡╨╜╤С╨╜╨╜╤Л╤Е ╨┐╨╛╨╗╨╡╨╣ (╨┤╨╗╤П API) ╨╕╨╗╨╕ [].
    """
    assignment: dict = {}
    changed_labels: list[str] = []
    for key, fk_attr in (
        ("domain", "domain_id"),
        ("profile", "profile_id"),
        ("owner", "owner_id"),
        ("group", "group_id"),
        ("country", "country_id"),
    ):
        if key not in validated:
            continue
        new_val = validated.get(key)
        if getattr(existing, fk_attr) == _assignment_fk_id(new_val):
            continue
        assignment[key] = new_val
        changed_labels.append(key)
    if not assignment:
        return []
    preserved = existing.updated_at
    for key, val in assignment.items():
        setattr(existing, key, val)
    existing.save(update_fields=_account_assignment_update_fields(assignment))
    _restore_account_updated_at(existing.pk, preserved)
    return changed_labels


def _restore_account_updated_at(account_id: int, preserved) -> None:
    """╨Я╨╛╤Б╨╗╨╡ ╨╜╨╡╤Г╤Б╨┐╨╡╤И╨╜╨╛╨│╨╛ refresh ╨╜╨╡ ╤В╤А╨╛╨│╨░╨╡╨╝ ┬л╨Ю╨▒╨╜╨╛╨▓╨╗╤С╨╜┬╗ ╨▓ UI (auto_now / ╤З╨░╤Б╤В╨╕╤З╨╜╤Л╨╣ save)."""
    if preserved is None:
        return
    Account.objects.filter(pk=account_id).update(updated_at=preserved)


def _stamp_new_account_updated_at(account_id: int) -> None:
    """╨Э╨╛╨▓╤Л╨╣ ╨░╨║╨║╨░╤Г╨╜╤В: ╤Д╨╕╨║╤Б╨╕╤А╨╛╨▓╨░╨╜╨╜╨░╤П ╨┤╨░╤В╨░ ╨▓╨╝╨╡╤Б╤В╨╛ now, ╤З╤В╨╛╨▒╤Л ╨▓╤Л╨┤╨╡╨╗╤П╤В╤М ┬л╨╡╤Й╤С ╨╜╨╡ ╨╛╨▒╨╜╨╛╨▓╨╗╤П╨╗╨╕╤Б╤М┬╗."""
    Account.objects.filter(pk=account_id).update(updated_at=NEW_ACCOUNT_UPDATED_AT)


def _account_refresh_baseline(account: Account) -> dict:
    from .refresh_cancel import account_refresh_baseline

    return account_refresh_baseline(account)


def _restore_account_refresh_baseline(account_id: int, baseline: dict | None) -> None:
    from .refresh_cancel import restore_account_refresh_baseline

    restore_account_refresh_baseline(account_id, baseline)


def _refresh_stats_trustworthy(account: Account, stats_before: dict[str, int]) -> bool:
    """╨г╤Б╨┐╨╡╤И╨╜╨╛╨╡ ╨╛╨▒╨╜╨╛╨▓╨╗╨╡╨╜╨╕╨╡ ╨┤╨╗╤П UI ┬л╨╛╨▒╨╜╨╛╨▓╨╗╤С╨╜┬╗: ╨╜╨╡ ╨╜╨╡╨┤╨╛╤Б╤В╤Г╨┐╨╜╤Л╨╣ ╨┐╤А╨╛╤Д╨╕╨╗╤М ╨╕ ╨╜╨╡ ┬л╨╛╨▒╨╜╤Г╨╗╨╡╨╜╨╕╨╡┬╗ ╨┐╤А╨╕ ╨╜╨╡╨╜╤Г╨╗╨╡╨▓╨╛╨╣ ╨▒╨░╨╖╨╡."""
    if bool(getattr(account, "profile_unavailable", False)):
        return False
    fields = ["follower_count", "like_count", "view_count", "post_count"]
    # Threads: ╨╝╨╡╤В╤А╨╕╨║╨╕ ╤Г╤А╨╛╨▓╨╜╤П ╨┐╤А╨╛╤Д╨╕╨╗╤П ╨╕ ╨░╨│╤А╨╡╨│╨░╤В╤Л ╨┐╨╛ ╨┐╨╛╤Б╤В╨░╨╝ ╨╜╨╡╤Б╤В╨░╨▒╨╕╨╗╤М╨╜╤Л (DOM, meta, ╨┐╤Г╤Б╤В╤Л╨╡ ╨╗╨░╨╣╨║╨╕).
    # ╨Ы╨╛╨╢╨╜╨╛╨╡ ┬л╨╛╨▒╨╜╤Г╨╗╨╡╨╜╨╕╨╡┬╗ ╨┐╨╛ follower/like/post ╨╗╨╛╨╝╨░╨╗╨╛ ╤Б╨╛╤Е╤А╨░╨╜╨╡╨╜╨╕╨╡ ╨╕ ╨╖╨░╨╗╨╕╨┐╨░╨╗ profile_unavailable.
    # ╨Ю╤Б╤В╨░╨▓╨╗╤П╨╡╨╝ ╤В╨╛╨╗╤М╨║╨╛ ╨╖╨░╤Й╨╕╤В╤Г ╨┐╨╛ view_count (╨┤╨╗╤П Threads ╨╛╨╜ ╨╡╤Й╤С ╨╕ max ╤Б ╨┐╤А╨╡╨┤╤Л╨┤╤Г╤Й╨╕╨╝ ╨▓ ╨┐╨░╨╣╨┐╨╗╨░╨╣╨╜╨╡).
    if account.platform == Platform.THREADS:
        fields = ["view_count"]
    elif account.platform == Platform.INSTAGRAM:
        # ╨Я╨╛╨┤╨┐╨╕╤Б╤З╨╕╨║╨╕ ╨╕ ╨╗╨░╨╣╨║╨╕ ╤Б╨╛ ╤Б╨║╤А╨░╨┐╨░ ╤З╨░╤Б╤В╨╛ 0 ╨┐╤А╨╕ ╨╗╨╕╨╝╨╕╤В╨░╤Е/╨░╨╜╤В╨╕╨▒╨╛╤В╨╡ ╨┐╤А╨╕ ╤В╨╛╨╝ ╨╢╨╡ ╨╢╨╕╨▓╨╛╨╝ ╨┐╤А╨╛╤Д╨╕╨╗╨╡;
        # ╨┐╨╛╨╗╨╜╨░╤П ╨┐╤А╨╛╨▓╨╡╤А╨║╨░ ╨║╨░╨║ ╤Г ┬л╨╛╨▒╤Л╤З╨╜╤Л╤Е┬╗ ╨┐╨╗╨░╤В╤Д╨╛╤А╨╝ ╨┤╨░╨▓╨░╨╗╨░ ╨╗╨╛╨╢╨╜╤Л╨╣ ╨╛╤В╨║╨░╨╖ ╨╕ HTTP 400 ╨▒╨╡╨╖ ╤Б╨╛╤Е╤А╨░╨╜╨╡╨╜╨╕╤П.
        # ╨Ч╨░╤Й╨╕╤Й╨░╨╡╨╝╤Б╤П ╨╛╤В ╨┐╨╛╨┤╨╛╨╖╤А╨╕╤В╨╡╨╗╤М╨╜╨╛╨│╨╛ ╨╛╨▒╨╜╤Г╨╗╨╡╨╜╨╕╤П ╨┐╨╛ ╨┐╤А╨╛╤Б╨╝╨╛╤В╤А╨░╨╝ ╨╕ ╤З╨╕╤Б╨╗╤Г ╨┐╨╛╤Б╤В╨╛╨▓.
        fields = ["view_count", "post_count"]
    elif account.platform == Platform.TIKTOK:
        # TikTok: ╨▓ UI ╨┐╤А╨╛╤Д╨╕╨╗╤М ╨╢╨╕╨▓╨╛╨╣ (╤А╨╛╨╗╨╕╨║╨╕ ╨╜╨░ ╨╝╨╡╤Б╤В╨╡), ╨░ follower/like ╤Б ╨┐╨░╤А╤Б╨╡╤А╨░ ╤З╨░╤Б╤В╨╛ 0
        # (╨░╨╜╤В╨╕╨▒╨╛╤В, ╨│╨╛╤Б╤В╤М, ╤Г╤А╨╡╨╖╨░╨╜╨╜╤Л╨╣ SSR) тАФ ╨╕╨╜╨░╤З╨╡ refresh ╨╛╤В╨║╨░╤В╤Л╨▓╨░╨╡╤В╤Б╤П, ╤Е╨╛╤В╤П ╨┐╨╛╤Б╤В╤Л ╨╛╨▒╨╜╨╛╨▓╨╕╨╗╨╕╤Б╤М.
        fields = ["view_count", "post_count"]
    elif account.platform == Platform.FACEBOOK:
        # ╨б╤Г╨╝╨╝╨░ ╨╗╨░╨╣╨║╨╛╨▓ ╨┐╨╛ ╨┐╨╛╤Б╤В╨░╨╝ ╨╝╨╛╨╢╨╡╤В ╨╖╨░╨║╨╛╨╜╨╛╨╝╨╡╤А╨╜╨╛ ╨╛╨▒╨╜╤Г╨╗╨╕╤В╤М╤Б╤П (╨▓╤Б╨╡ ╨┐╨╛╤Б╤В╤Л тЙд MIN_VIEWS ╨┤╨╗╤П ╨┤╨╡╤В╨░╨╗╤М╨╜╤Л╤Е ╨╗╨░╨╣╨║╨╛╨▓).
        # ╨Я╨╛╨┤╨┐╨╕╤Б╤З╨╕╨║╨╕ ╤Б╨╛ ╤Б╨║╤А╨░╨┐╨░ ╤З╨░╤Б╤В╨╛ 0 ╨┐╤А╨╕ ╤В╨╛╨╣ ╨╢╨╡ ╨╢╨╕╨▓╨╛╨╣ ╤Б╤В╤А╨░╨╜╨╕╤Ж╨╡ (DOM / headless / ╤П╨╖╤Л╨║ ╨▒╨╗╨╛╨║╨░) тАФ
        # ╨╡╤Б╨╗╨╕ ╤В╤А╨╡╨▒╨╛╨▓╨░╤В╤М ┬л╨╜╨╡ ╨╛╨▒╨╜╤Г╨╗╤П╤В╤М follower_count┬╗, ╨▓╨╡╤Б╤М refresh ╨╛╤В╨║╨░╤В╤Л╨▓╨░╨╡╤В╤Б╤П ╨╕ **╨╜╨╡ ╤Б╨╛╤Е╤А╨░╨╜╤П╤О╤В╤Б╤П**
        # ╨╗╨░╨╣╨║╨╕ ╨┐╨╛╤Б╤В╨╛╨▓ ╨┐╨╛╤Б╨╗╨╡ enrich. ╨Э╨╡ ╨▓╨║╨╗╤О╤З╨░╨╡╨╝ follower_count ╨╕ like_count ╨▓ ╤Н╤В╤Г ╨┐╤А╨╛╨▓╨╡╤А╨║╤Г.
        fields = ["view_count", "post_count"]
    active_post_count = _posts_for_account_stats(account).count()
    for f in fields:
        prev = int(stats_before.get(f, 0) or 0)
        cur = int(getattr(account, f, 0) or 0)
        if prev > 0 and cur == 0:
            if (
                account.platform == Platform.TIKTOK
                and f == "post_count"
                and active_post_count == 0
            ):
                # ╨б╨▒╤А╨░╤Б╤Л╨▓╨░╨╡╨╝ ╨╗╨╛╨╢╨╜╤Л╨╣ videoCount ╨╕╨╖ ╤И╨░╨┐╨║╨╕, ╨║╨╛╨│╨┤╨░ ╨┐╨╛╤Б╤В╨╛╨▓ ╨▓ ╨С╨Ф ╨╜╨╡╤В.
                continue
            return False
    return True

# ╨Я╨░╤А╤Б╨╡╤А╤Л (╨╛╤Б╨╛╨▒╨╡╨╜╨╜╨╛ Instagram og:image ╨┐╤А╨╕ ╨░╨╜╤В╨╕╨▒╨╛╤В╨╡) ╨╕╨╜╨╛╨│╨┤╨░ ╨╛╤В╨┤╨░╤О╤В ╨┐╤Г╤Б╤В╤Г╤О ╤Б╤В╤А╨╛╨║╤Г тАФ
# ╨╜╨╡ ╨╖╨░╤В╨╕╤А╨░╨╡╨╝ ╤Г╨╢╨╡ ╤Б╨╛╤Е╤А╨░╨╜╤С╨╜╨╜╤Л╨╣ CDN-URL, ╨╕╨╜╨░╤З╨╡ ╨▓ UI ╨┐╤А╨╛╨┐╨░╨┤╨░╨╡╤В ╨░╨▓╨░╤В╨░╤А╨║╨░ ╨┤╨╛ ╤Б╨╗╨╡╨┤╤Г╤О╤Й╨╡╨│╨╛ ╤Г╨┤╨░╤З╨╜╨╛╨│╨╛ ╨┐╨░╤А╤Б╨░.
_SKIP_EMPTY_STR_UPDATE = frozenset({"avatar_url"})

_PLATFORM_WORKERS = {
    Platform.TIKTOK: Path(__file__).parent.parent / "platforms" / "tiktok" / "worker.py",
    Platform.INSTAGRAM: Path(__file__).parent.parent / "platforms" / "instagram" / "worker.py",
    Platform.X: Path(__file__).parent.parent / "platforms" / "x" / "worker.py",
    Platform.THREADS: Path(__file__).parent.parent / "platforms" / "threads" / "worker.py",
    Platform.FACEBOOK: Path(__file__).parent.parent / "platforms" / "facebook" / "worker.py",
    Platform.TELEGRAM: Path(__file__).parent.parent / "platforms" / "telegram" / "worker.py",
    Platform.RUMBLE: Path(__file__).parent.parent / "platforms" / "rumble" / "worker.py",
    Platform.REDDIT: Path(__file__).parent.parent / "platforms" / "reddit" / "worker.py",
}


def _normalize_instagram_username_key(username: str) -> str:
    return (username or "").lstrip("@").strip().lower()


def _get_float_setting(name: str, default: float) -> float:
    raw = getattr(settings, name, None)
    if raw is None:
        raw = os.environ.get(name)
    if raw is None or (isinstance(raw, str) and not str(raw).strip()):
        return default
    try:
        return float(raw)
    except (TypeError, ValueError):
        return default


def _refresh_all_delay_seconds(account: Account) -> float:
    """
    Platform-aware pause between refresh_all iterations.

    Instagram is already preloaded in batch and generally doesn't need extra delay.
    Other platforms keep a short jitter to reduce burst traffic / anti-bot friction.
    Facebook: 2тАУ5 ╨╝╨╕╨╜ ╨╝╨╡╨╢╨┤╤Г ╨░╨║╨║╨░╤Г╨╜╤В╨░╨╝╨╕ (120тАУ300 ╤Б) тАФ Playwright + ╨░╨╜╤В╨╕╨▒╨╛╤В.
    TikTok: ╨┐╨░╤Г╨╖╨░ ╨╝╨╡╨╢╨┤╤Г ╨░╨║╨║╨░╤Г╨╜╤В╨░╨╝╨╕ 5тАУ10 ╤Б (env REFRESH_ALL_DELAY_TIKTOK_*).
    YouTube: ╨┐╨░╤Г╨╖╨░ 5тАУ10 ╤Б ╨╝╨╡╨╢╨┤╤Г ╨░╨║╨║╨░╤Г╨╜╤В╨░╨╝╨╕ тАФ ╤Б╨╜╨╕╨╢╨░╨╡╤В ╤А╨╕╤Б╨║ ╨║╨▓╨╛╤В/╨▒╨╗╨╛╨║╨╕╤А╨╛╨▓╨╛╨║ ╨┐╤А╨╕ ╤Б╨╡╤А╨╕╨╕ ╨╖╨░╨┐╤А╨╛╤Б╨╛╨▓.
    Rumble: ╨┐╨░╤Г╨╖╨░ 20тАУ40 ╤Б (env REFRESH_ALL_DELAY_RUMBLE_*) тАФ Cloudflare + Playwright.
    """
    platform_defaults: dict[str, tuple[float, float]] = {
        Platform.INSTAGRAM: (0.0, 0.0),
        Platform.TIKTOK: (5.0, 10.0),
        Platform.X: (0.8, 1.6),
        Platform.THREADS: (2.0, 4.0),
        Platform.FACEBOOK: (120.0, 300.0),
        Platform.YOUTUBE: (5.0, 10.0),
        Platform.TELEGRAM: (0.3, 0.8),
        Platform.RUMBLE: (20.0, 40.0),
        Platform.REDDIT: (0.4, 0.9),
    }
    dmin, dmax = platform_defaults.get(account.platform, (3.0, 7.0))
    key = account.platform.upper()
    lo = _get_float_setting(f"REFRESH_ALL_DELAY_{key}_MIN", dmin)
    hi = _get_float_setting(f"REFRESH_ALL_DELAY_{key}_MAX", dmax)
    # Backward-compatible global clamp/fallback
    global_lo = _get_float_setting("REFRESH_ALL_DELAY_MIN", lo)
    global_hi = _get_float_setting("REFRESH_ALL_DELAY_MAX", hi)
    # REFRESH_ALL_DELAY_MIN/MAX ╨┐╨╛ ╤Г╨╝╨╛╨╗╤З╨░╨╜╨╕╤О 0 тАФ ╤Н╤В╨╛ ┬л╨▒╨╡╨╖ ╨│╨╗╨╛╨▒╨░╨╗╤М╨╜╨╛╨╣ ╨╜╨░╨┤╤Б╤В╤А╨╛╨╣╨║╨╕┬╗,
    # ╨░ ╨╜╨╡ ┬л╨╛╨▒╨╜╤Г╨╗╨╕╤В╤М ╨╜╨╕╨╢╨╜╤О╤О ╨│╤А╨░╨╜╨╕╤Ж╤Г ╨┐╨░╤Г╨╖╤Л┬╗ (╨╕╨╜╨░╤З╨╡ min(..., 0) ╨╗╨╛╨╝╨░╨╡╤В ╨┤╨╢╨╕╤В╤В╨╡╤А ╨┐╨╗╨░╤В╤Д╨╛╤А╨╝).
    if global_lo <= 0 and global_hi <= 0:
        a = max(0.0, min(lo, hi))
        b = max(lo, hi)
    else:
        a = max(0.0, min(lo, hi, global_lo, global_hi))
        b = max(lo, hi, global_lo, global_hi)
    if b <= 0:
        return 0.0
    if a == b:
        return a
    return random.uniform(a, b)


def _refresh_all_cooldown_seconds(
    account: Account,
    exc: BaseException | None = None,
) -> float:
    """╨Я╨░╤Г╨╖╨░ ╨╝╨╡╨╢╨┤╤Г ╨░╨║╨║╨░╤Г╨╜╤В╨░╨╝╨╕ ╨▓ ╤Б╨╡╤А╨╕╨╣╨╜╨╛╨╝ refresh; 0 ╨╡╤Б╨╗╨╕ ╨┐╤А╨╛╤Д╨╕╨╗╤М ╨╜╨╡ ╨╜╨░╨╣╨┤╨╡╨╜/╤Г╨┤╨░╨╗╤С╨╜."""
    if exc is not None and is_profile_unavailable_error(str(exc)):
        return 0.0
    if bool(getattr(account, "profile_unavailable", False)):
        return 0.0
    return _refresh_all_delay_seconds(account)


def _refresh_int_env(name: str, default: int, *, min_v: int = 1, max_v: int = 32) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        val = int(str(raw).strip())
    except Exception:
        return default
    return max(min_v, min(max_v, val))


def _refresh_worker_count(*, account_count: int | None = None) -> int:
    """╨Ь╨╕╨╜╨╕╨╝╤Г╨╝ ╨▓╨╛╤А╨║╨╡╤А╨╛╨▓ ╨╕╨╖ AUTO_REFRESH_WORKERS (╨┐╨╛ ╤Г╨╝╨╛╨╗╤З╨░╨╜╨╕╤О 3)."""
    try:
        n = int(str(os.environ.get("AUTO_REFRESH_WORKERS", "3")).strip() or "3")
    except Exception:
        n = 3
    n = max(1, min(16, n))
    if account_count is not None:
        n = min(n, max(1, int(account_count)))
    return n


def _parallel_refresh_worker_count(accounts: list[Account]) -> int:
    """
    ╨Т╨╛╤А╨║╨╡╤А╤Л ╨┤╨╗╤П bulk / refresh_all: ╨┐╨░╤А╨░╨╗╨╗╨╡╨╗╤М╨╜╨╛ ╤А╨░╨╖╨╜╤Л╨╡ ╨┐╨╗╨░╤В╤Д╨╛╤А╨╝╤Л.
    ╨С╨╡╤А╤С╨╝ max(AUTO_REFRESH_WORKERS, ╤З╨╕╤Б╨╗╨╛ ╨┐╨╗╨░╤В╤Д╨╛╤А╨╝ ╨▓ ╨┐╨░╨║╨╡╤В╨╡), ╨▓ ╨┐╤А╨╡╨┤╨╡╨╗╨░╤Е ╨╗╨╕╨╝╨╕╤В╨╛╨▓ concurrency.
    """
    n = len(accounts)
    if n <= 1:
        return 1
    platforms = {a.platform for a in accounts}
    limits = _refresh_platform_limits(accounts)
    max_by_limits = sum(limits.get(p, 1) for p in platforms)
    env_floor = _refresh_worker_count(account_count=n)
    cross_platform = min(n, len(platforms), max(1, max_by_limits))
    target = max(env_floor, cross_platform)
    return max(1, min(16, n, max(1, max_by_limits), target))


def _keep_bulk_refresh_running(state: AutoRefreshState) -> None:
    """╨Т╨╛╤Б╤Б╤В╨░╨╜╨╛╨▓╨╕╤В╤М is_running, ╨╡╤Б╨╗╨╕ ╤Д╨╗╨░╨│ ╤Б╨▒╤А╨╛╤Б╨╕╨╗╨╕ ╨┐╨╛╨▒╨╛╤З╨╜╤Л╨╝ ╨┐╤А╨╛╤Ж╨╡╤Б╤Б╨╛╨╝, ╨░ ╨┐╨╛╤В╨╛╨║ bulk ╨╡╤Й╤С ╤А╨░╨▒╨╛╤В╨░╨╡╤В."""
    from .refresh_state import keep_auto_refresh_run_alive

    keep_auto_refresh_run_alive(state)


def _refresh_platform_limits(accs: list[Account]) -> dict[str, int]:
    defaults: dict[str, int] = {
        Platform.TIKTOK: 1,
        Platform.INSTAGRAM: 1,
        Platform.THREADS: 1,
        Platform.FACEBOOK: 1,
        Platform.RUMBLE: 1,
        Platform.TELEGRAM: 1,
        Platform.X: 1,
        Platform.REDDIT: 2,
        Platform.YOUTUBE: 1,
    }
    limits: dict[str, int] = {}
    for p in {a.platform for a in accs}:
        env_key = f"AUTO_REFRESH_CONCURRENCY_{str(p).upper()}"
        limits[p] = _refresh_int_env(env_key, defaults.get(p, 1), min_v=1, max_v=8)
    return limits


def _interleave_accounts_by_platform(items: list[Account]) -> list[Account]:
    from .refresh_queue import interleave_accounts_by_platform

    return interleave_accounts_by_platform(items)


from .db_connections import (  # noqa: E402 тАФ re-export for apps / tests
    ensure_fresh_db_connections,
    release_db_for_long_task,
    run_with_db_reconnect,
    stale_db_connection_error as _stale_db_connection_error,
)


def humanize_refresh_run_detail(exc: BaseException) -> str:
    """╨Ъ╨╛╤А╨╛╤В╨║╨╕╨╣ ╤В╨╡╨║╤Б╤В ╨╛╤И╨╕╨▒╨║╨╕ ╨┤╨╗╤П run_detail / CSV (╨▒╨╡╨╖ ╨░╨╜╨│╨╗. psycopg ╨┐╨╛ ╤Г╨╝╨╛╨╗╤З╨░╨╜╨╕╤О)."""
    if _stale_db_connection_error(exc):
        return (
            "╨б╨╛╨╡╨┤╨╕╨╜╨╡╨╜╨╕╨╡ ╤Б ╨▒╨░╨╖╨╛╨╣ ╤А╨░╨╖╨╛╤А╨▓╨░╨╜╨╛ (╨┤╨╛╨╗╨│╨╕╨╣ ╨╖╨░╨┐╤А╨╛╤Б ╨╕╨╗╨╕ ╨┐╨╡╤А╨╡╨╖╨░╨┐╤Г╤Б╨║ Django). "
            "╨Ч╨░╨┐╤Г╤Б╤В╨╕╤В╨╡ ╨╛╨▒╨╜╨╛╨▓╨╗╨╡╨╜╨╕╨╡ ╤Б╨╜╨╛╨▓╨░."
        )
    detail = str(exc).replace("\r\n", " ").replace("\n", " ").strip()
    if len(detail) > 800:
        detail = detail[:797] + "..."
    return detail


def _format_refresh_error(account: Account, exc: BaseException) -> tuple[str, int]:
    _mark_profile_unavailable_if_applicable(account, exc)
    if isinstance(exc, ValueError):
        return user_visible_profile_unavailable_error(str(exc)), status.HTTP_400_BAD_REQUEST
    if _stale_db_connection_error(exc):
        return humanize_refresh_run_detail(exc), status.HTTP_500_INTERNAL_SERVER_ERROR
    # 500: ╨▓╨╜╤Г╤В╤А╨╡╨╜╨╜╤П╤П ╨╛╤И╨╕╨▒╨║╨░ ╤Б╤К╤С╨╝╨░/╨С╨Ф тАФ ╨╜╨╡ ┬л╤И╨╗╤О╨╖┬╗; ╤В╨╡╨║╤Б╤В ╨▓ detail ╨┤╨╗╤П ╨║╨╗╨╕╨╡╨╜╤В╨░ ╨╕ ╨╗╨╛╨│ ╨┤╨╗╤П ╤Б╨╡╤А╨▓╨╡╤А╨░.
    return f"╨Ю╤И╨╕╨▒╨║╨░: {exc}", status.HTTP_500_INTERNAL_SERVER_ERROR


def _refresh_account_for_api(account: Account, *, scraped: dict | None = None) -> tuple[Account | None, str | None, int | None]:
    from .refresh_cancel import RefreshCancelledError
    from .refresh_priority import account_refresh_priority_session

    try:
        with account_refresh_priority_session():
            return _refresh_with_retry(account, scraped=scraped), None, None
    except RefreshCancelledError:
        return None, "╨Ю╤Б╤В╨░╨╜╨╛╨▓╨╗╨╡╨╜╨╛ ╨┐╨╛╨╗╤М╨╖╨╛╨▓╨░╤В╨╡╨╗╨╡╨╝", None
    except Exception as exc:
        from accounts.scrape_fallback_recovery import (
            notify_playwright_batch_errors,
            try_apify_recovery_after_playwright_failure,
        )
        from accounts.tiktok_scrape_fallback import BatchScrapeContext

        batch_ctx = BatchScrapeContext.for_accounts([account])
        notify_playwright_batch_errors(account, exc, batch_ctx=batch_ctx)
        try:
            import uuid

            from accounts.models import ApifyRefreshJobTrigger

            recovered = try_apify_recovery_after_playwright_failure(
                account,
                exc,
                batch_ctx=batch_ctx,
                trigger=ApifyRefreshJobTrigger.MANUAL,
                parent_batch_id=uuid.uuid4(),
            )
            if recovered is not None:
                return recovered, None, None
        except Exception as apify_exc:
            exc = apify_exc
        logger.warning(
            "refresh.account_failed",
            extra={
                "account_id": getattr(account, "id", None),
                "platform": getattr(account, "platform", None),
                "username": getattr(account, "username", None),
                "exc_type": type(exc).__name__,
            },
            exc_info=True,
        )
        detail, code = _format_refresh_error(account, exc)
        return None, detail, code


def _refresh_link_clicks_for_accounts(accounts: list[Account], *, log_prefix: str = "refresh") -> dict | None:
    """
    ╨в╨╛ ╨╢╨╡, ╤З╤В╨╛ POST /api/accounts/refresh-link-clicks/ тАФ ╨▒╨░╤В╤З ╨╕╨╖ Links API
    + ╨║╤Н╤И ╨╕╨╜╨┤╨╡╨║╤Б╨░ ╨┤╨╗╤П sync_link_clicks_for_account ╨▓ _apply_refresh.
    """
    from integrations.links_client import links_api_configured
    from integrations.links_sync import begin_refresh_all_links, refresh_link_clicks_batch

    if not accounts:
        return None
    if not links_api_configured():
        print(
            f"[{log_prefix}] link clicks: skip (Links API ╨╜╨╡ ╨╜╨░╤Б╤В╤А╨╛╨╡╨╜)",
            file=sys.stderr,
            flush=True,
        )
        return None
    result = refresh_link_clicks_batch(accounts)
    begin_refresh_all_links(accounts)
    print(
        f"[{log_prefix}] link clicks: updated={result.get('updated', 0)} "
        f"changed={result.get('changed', 0)} skipped={result.get('skipped', 0)} "
        f"errors={len(result.get('errors') or [])}",
        file=sys.stderr,
        flush=True,
    )
    return result


def _prewarm_workers(accounts: list[Account], *, wait_browser_ready: bool = False) -> None:
    """
    Start daemon workers upfront for platforms present in refresh_all batch.
    This opens one browser window per used platform at the beginning.
    """
    from platforms.worker_pool import prewarm_workers

    used_platforms = {acc.platform for acc in accounts}
    worker_paths: list[Path] = []
    skip_rumble = False
    try:
        from platforms.rumble.scraper import skip_playwright_prewarm

        skip_rumble = skip_playwright_prewarm()
    except Exception:
        pass
    for platform in sorted(used_platforms):
        if skip_rumble and platform == Platform.RUMBLE:
            continue
        worker = _PLATFORM_WORKERS.get(platform)
        if worker and worker.exists():
            worker_paths.append(worker)
    if not worker_paths:
        return
    try:
        prewarm_workers(worker_paths, wait_browser_ready=wait_browser_ready)
    except Exception as e:
        logger.warning("refresh.prewarm_failed", extra={"error": str(e)})


_refresh_all_start_lock = threading.Lock()


def _mark_bulk_refresh_queued_cancelled(state: AutoRefreshState) -> None:
    rd = dict(state.run_detail or {})
    items = [dict(x) for x in (rd.get("items") or [])]
    changed = False
    for i, it in enumerate(items):
        if (it.get("status") or "").strip() == "queued":
            items[i] = {**it, "status": "cancelled", "detail": "╨Ю╤Б╤В╨░╨╜╨╛╨▓╨╗╨╡╨╜╨╛ ╨┐╨╛╨╗╤М╨╖╨╛╨▓╨░╤В╨╡╨╗╨╡╨╝"}
            changed = True
    if changed:
        rd["items"] = items
        state.run_detail = rd
        state.save(update_fields=["run_detail", "updated_at"])


def _run_bulk_refresh_background(account_ids: list[int]) -> None:
    from django.db import close_old_connections

    from .refresh_cancel import RefreshCancelledError

    close_old_connections()
    state = AutoRefreshState.get()
    id_ints = [int(x) for x in account_ids]
    by_id = {a.id: a for a in Account.objects.filter(id__in=id_ints).select_related("profile")}
    ordered: list[Account] = []
    for i in id_ints:
        if i in by_id:
            ordered.append(by_id[i])
    if not ordered:
        state.is_running = False
        state.finished_at = timezone.now()
        state.last_error = "╨Р╨║╨║╨░╤Г╨╜╤В╤Л ╨╜╨╡ ╨╜╨░╨╣╨┤╨╡╨╜╤Л"
        state.save(update_fields=["is_running", "finished_at", "last_error", "updated_at"])
        return

    from .refresh_queue import order_accounts_for_refresh

    accounts = order_accounts_for_refresh(ordered)
    # ╨Ч╨┤╨╡╤Б╤М ╨░╨║╨║╨░╤Г╨╜╤В╤Л ╨▓╤Л╨▒╤А╨░╨╜╤Л ╤А╤Г╨║╨░╨╝╨╕ тАФ ╨┐╤А╨░╨▓╨╕╨╗╨╛ ┬л╨╜╨╡ ╤В╤А╨╛╨│╨░╤В╤М ╨╜╨╡╨┤╨░╨▓╨╜╨╛ ╨╛╨▒╨╜╨╛╨▓╨╗╤С╨╜╨╜╤Л╨╡┬╗
    # ╨║ ╨╜╨╕╨╝ ╨╜╨╡ ╨╛╤В╨╜╨╛╤Б╨╕╤В╤Б╤П: ╨╛╨╜╨╛ ╨┤╨╗╤П ╨┐╤А╨╛╨│╨╛╨╜╨╛╨▓ ╨┐╨╛ ╤А╨░╤Б╨┐╨╕╤Б╨░╨╜╨╕╤О, ╤З╤В╨╛╨▒╤Л ╨╜╨╡ ╤Б╨║╤А╨╡╤Б╤В╨╕ ╨▓╤Б╤О ╤Б╨╡╤В╤М
    # ╨╖╨░╨╜╨╛╨▓╨╛. ╨а╨░╨╜╤М╤И╨╡ ╨▓╤Л╨▒╨╛╤А ╤В╤А╤С╤Е ╨░╨║╨║╨░╤Г╨╜╤В╨╛╨▓ ╨╕ ┬л╨Ю╨▒╨╜╨╛╨▓╨╕╤В╤М┬╗ ╨┤╨░╨▓╨░╨╗╨╕ ╨┐╤А╨╛╨│╨╛╨╜ ╨╜╨░ ╤Б╨╡╨║╤Г╨╜╨┤╤Г
    # ╤Б ╤В╤А╨╡╨╝╤П ┬л╨┐╤А╨╛╨┐╤Г╤Й╨╡╨╜╨╛┬╗ тАФ ╤Б╨╛ ╤Б╤В╨╛╤А╨╛╨╜╤Л ╤Н╤В╨╛ ╨▓╤Л╨│╨╗╤П╨┤╨╡╨╗╨╛ ╨║╨░╨║ ┬л╨║╨╜╨╛╨┐╨║╨░ ╨╜╨╡ ╤А╨░╨▒╨╛╤В╨░╨╡╤В┬╗.
    skip_recent_hours, cutoff = 0, None
    from .refresh_priority import account_refresh_priority_session

    stop_requested = threading.Event()
    state_lock = threading.Lock()
    warm_tracker = None
    try:
        with account_refresh_priority_session():
            try:
                from platforms.worker_pool import (
                    clear_playwright_refresh_force_stop,
                    shutdown_all_workers,
                )

                # ╨Ч╨░╨║╤А╤Л╨▓╨░╨╡╨╝ ╨┤╨╡╨╝╨╛╨╜╤Л, ╨╛╤Б╤В╨░╨▓╤И╨╕╨╡╤Б╤П ╨╛╤В ╨┐╤А╨╛╤И╨╗╨╛╨│╨╛ ╨┐╤А╨╛╨│╨╛╨╜╨░.
                shutdown_all_workers()
                # ╨Ш ╤Б╤А╨░╨╖╤Г ╤Б╨╜╨╕╨╝╨░╨╡╨╝ ╤Д╨╗╨░╨│. shutdown_all_workers() ╨▓╨╖╨▓╨╛╨┤╨╕╤В force_stop,
                # ╤З╤В╨╛╨▒╤Л ╨┤╨╡╨╝╨╛╨╜╤Л ╨╜╨╡ ╨┐╨╛╨┤╨╜╤П╨╗╨╕╤Б╤М ╨╛╨▒╤А╨░╤В╨╜╨╛, ╨┐╨╛╨║╨░ ╨╕╨┤╤С╤В kill, тАФ ╨╜╨╛ ╨╖╨┤╨╡╤Б╤М ╨╝╤Л
                # ╤Б╨░╨╝╨╕ ╨╢╨╡ ╤Б╨╛╨▒╨╕╤А╨░╨╡╨╝╤Б╤П ╨╕╤Е ╨┐╨╛╨┤╨╜╨╕╨╝╨░╤В╤М. ╨С╨╡╨╖ ╤Н╤В╨╛╨│╨╛ ╨║╨░╨╢╨┤╤Л╨╣ ╨░╨║╨║╨░╤Г╨╜╤В,
                # ╨║╨╛╤В╨╛╤А╨╛╨╝╤Г ╨╜╤Г╨╢╨╡╨╜ ╨▒╤А╨░╤Г╨╖╨╡╤А, ╨┐╨╛╨╗╤Г╤З╨░╨╗ ┬л╨Ю╤Б╤В╨░╨╜╨╛╨▓╨╗╨╡╨╜╨╛ ╨┐╨╛╨╗╤М╨╖╨╛╨▓╨░╤В╨╡╨╗╨╡╨╝┬╗ ╨▒╨╡╨╖
                # ╨╡╨┤╨╕╨╜╨╛╨╣ ╨┐╨╛╨┐╤Л╤В╨║╨╕: 22 ╨╕╨╖ 25 ╨▓ ╨╛╨┤╨╜╨╛╨╝ ╨┐╤А╨╛╨│╨╛╨╜╨╡, 18 ╨╕╨╖ 22 ╨▓ ╨┤╤А╤Г╨│╨╛╨╝, ╨┐╤А╨╕
                # ╨╜╤Г╨╗╨╡ ╨╜╨░╤Б╤В╨╛╤П╤Й╨╕╤Е ╨╛╤В╨║╨░╨╖╨╛╨▓. ╨в╨░╨║ ╨╢╨╡ ╨┐╨╛╤Б╤В╤Г╨┐╨░╨╡╤В
                # interrupt_competing_playwright_for_account_refresh ╨▓ ╤Б╨▓╨╛╤С╨╝ finally.
                clear_playwright_refresh_force_stop()
            except Exception:
                pass

            from .parallel_account_queue import ParallelAccountQueue
            from .refresh_all_warm import RefreshAllWarmTracker

            warm_tracker = RefreshAllWarmTracker(accounts, label="bulk_refresh")
            state.refresh_from_db(fields=["cancel_requested"])
            if state.cancel_requested:
                stop_requested.set()
                state.last_error = "╨Ю╨▒╨╜╨╛╨▓╨╗╨╡╨╜╨╕╨╡ ╨╛╤Б╤В╨░╨╜╨╛╨▓╨╗╨╡╨╜╨╛ ╨┐╨╛╨╗╤М╨╖╨╛╨▓╨░╤В╨╡╨╗╨╡╨╝."
                state.save(update_fields=["last_error", "updated_at"])
            errors_out: list[dict] = []
            import uuid

            from accounts.models import ApifyRefreshJobTrigger
            from .scrape_backend import (
                accounts_needing_playwright,
                facebook_playwright_warm_needed,
                refresh_account_via_apify_sync,
                should_use_apify_for_account,
            )

            apify_batch_id = uuid.uuid4()
            with state_lock:
                state.refresh_from_db(fields=["run_detail"])
                rd_batch = dict(state.run_detail or {})
                rd_batch["apify_batch_id"] = str(apify_batch_id)
                state.run_detail = rd_batch
                state.save(update_fields=["run_detail", "updated_at"])
            try:
                from platforms.apify.abort import abort_active_apify_jobs

                aborted = abort_active_apify_jobs()
                if aborted:
                    print(
                        f"[bulk_refresh] ╨╛╤В╨╝╨╡╨╜╨╡╨╜╨╛ ╨░╨║╤В╨╕╨▓╨╜╤Л╤Е Apify jobs: {aborted}",
                        file=sys.stderr,
                        flush=True,
                    )
            except Exception as exc:
                print(f"[bulk_refresh] abort Apify jobs failed: {exc}", file=sys.stderr)
            from platforms.apify.batch_guard import enter_sync_apify_batch, leave_sync_apify_batch

            enter_sync_apify_batch(apify_batch_id)
            from .facebook_refresh_lane import (
                begin_facebook_batch,
                end_facebook_batch,
                batch_has_facebook,
                platform_claim_filter,
                submit_refresh_workers,
                try_mark_facebook_account_started,
                allocate_worker_slot,
                ensure_facebook_playwright_daemon_ready,
            )

            has_fb_accounts = batch_has_facebook(accounts)
            begin_facebook_batch()
            try:
                has_facebook = facebook_playwright_warm_needed(accounts)
                from .scrape_backend import BatchScrapeContext

                batch_scrape = BatchScrapeContext.for_accounts(accounts)
                fb_batch_guard = None
                if has_facebook:
                    from platforms.facebook.rate_limit import FacebookRefreshBatchGuard

                    fb_fb = batch_scrape.facebook_fallback
                    if fb_fb is None or not fb_fb.enabled:
                        fb_batch_guard = FacebookRefreshBatchGuard()

                if not stop_requested.is_set():
                    preload: dict[str, dict] = {}
                else:
                    preload = {}

                platform_limits = _refresh_platform_limits(accounts)
                account_queue = ParallelAccountQueue(len(accounts), platform_limits)
                from .refresh_skip_recent import apply_upfront_skip_recent

                apply_upfront_skip_recent(
                    accounts,
                    cutoff=cutoff,
                    skip_recent_hours=skip_recent_hours,
                    account_queue=account_queue,
                )
                worker_count = _parallel_refresh_worker_count(accounts)

                with state_lock:
                    state.refresh_from_db(fields=["run_detail"])
                    rd = dict(state.run_detail or {})
                    rd["worker_count"] = worker_count
                    state.run_detail = rd
                    state.save(update_fields=["run_detail", "updated_at"])

                thread_slot_map: dict[int, int] = {}
                thread_slot_lock = threading.Lock()
                _fb_daemon_prepared = threading.Event()

                def _worker_slot(*, facebook_lane: bool) -> int:
                    return allocate_worker_slot(
                        facebook_lane=facebook_lane,
                        thread_slot_map=thread_slot_map,
                        thread_slot_lock=thread_slot_lock,
                    )

                def _mark_progress(*, success: bool, failed: bool, last_error: str = "") -> None:
                    _keep_bulk_refresh_running(state)
                    with state_lock:
                        state.processed_accounts += 1
                        if success:
                            state.success_accounts += 1
                        if failed:
                            state.failed_accounts += 1
                            state.last_error = last_error
                        state.save(update_fields=[
                            "processed_accounts", "success_accounts", "failed_accounts",
                            "last_error", "updated_at",
                        ])

                def _worker(facebook_lane: bool) -> None:
                    if facebook_lane and not _fb_daemon_prepared.is_set():
                        try:
                            ensure_facebook_playwright_daemon_ready()
                        except Exception as exc:
                            print(
                                f"[bulk_refresh] Facebook daemon: {exc}",
                                file=sys.stderr,
                                flush=True,
                            )
                        _fb_daemon_prepared.set()
                    while True:
                        if stop_requested.is_set():
                            return
                        with state_lock:
                            state.refresh_from_db(fields=["cancel_requested"])
                            if bool(state.cancel_requested):
                                state.last_error = "╨Ю╨▒╨╜╨╛╨▓╨╗╨╡╨╜╨╕╨╡ ╨╛╤Б╤В╨░╨╜╨╛╨▓╨╗╨╡╨╜╨╛ ╨┐╨╛╨╗╤М╨╖╨╛╨▓╨░╤В╨╡╨╗╨╡╨╝."
                                state.save(update_fields=["last_error", "updated_at"])
                                stop_requested.set()
                                return

                        idx = account_queue.claim(
                            lambda i: accounts[i].platform,
                            stop_event=stop_requested,
                            platform_filter=platform_claim_filter(facebook_lane=facebook_lane),
                        )
                        if idx is None:
                            return

                        close_old_connections()
                        _keep_bulk_refresh_running(state)
                        account = accounts[idx]
                        if (
                            facebook_lane
                            and account.platform == Platform.FACEBOOK
                            and not try_mark_facebook_account_started(account.id)
                        ):
                            account_queue.abandon(idx, account.platform)
                            continue
                        from .warm_run_detail import is_refresh_cancel_requested

                        if is_refresh_cancel_requested():
                            stop_requested.set()
                            return
                        release_db_for_long_task()
                        warm_tracker.wait_warm_before_refresh(account.platform)
                        if is_refresh_cancel_requested():
                            stop_requested.set()
                            return
                        attempted_network = False
                        refresh_failure_exc: BaseException | None = None
                        refresh_baseline = None
                        try:
                            if stop_requested.is_set():
                                return

                            slot = _worker_slot(facebook_lane=facebook_lane)
                            with state_lock:
                                state.current_account = f"{account.platform}/@{account.username}"
                                state.save(update_fields=["current_account", "updated_at"])
                            _persist_auto_refresh_run_item(account.id, status="running", worker=slot)

                            if cutoff is not None and account.updated_at and account.updated_at >= cutoff:
                                skip_detail = f"╨╜╨╡╨┤╨░╨▓╨╜╨╛ ╨╛╨▒╨╜╨╛╨▓╨╗╤С╨╜ (тЙд {skip_recent_hours} ╤З)"
                                _persist_auto_refresh_run_item(
                                    account.id,
                                    status="skipped",
                                    worker=None,
                                    detail=skip_detail,
                                )
                                _mark_progress(success=True, failed=False)
                            elif (
                                account.platform == Platform.FACEBOOK
                                and fb_batch_guard is not None
                                and not should_use_apify_for_account(account, batch_ctx=batch_scrape)
                                and fb_batch_guard.is_tripped()
                            ):
                                skip_detail = fb_batch_guard.skip_detail()
                                _persist_auto_refresh_run_item(
                                    account.id,
                                    status="skipped",
                                    worker=None,
                                    detail=skip_detail,
                                )
                                _mark_progress(success=True, failed=False)
                            elif (
                                account.platform == Platform.TIKTOK
                                and batch_scrape.tiktok_captcha_tripped()
                                and not should_use_apify_for_account(account, batch_ctx=batch_scrape)
                            ):
                                err_detail = batch_scrape.tiktok_captcha_skip_detail()
                                _persist_auto_refresh_run_item(
                                    account.id,
                                    status="error",
                                    worker=None,
                                    detail=err_detail,
                                )
                                _mark_progress(success=False, failed=True, last_error=err_detail)
                                errors_out.append({"id": account.id, "detail": err_detail})
                            elif should_use_apify_for_account(account, batch_ctx=batch_scrape):
                                from accounts.models import ApifyRefreshJob, ApifyRefreshJobStatus

                                attempted_network = True
                                try:
                                    refresh_account_via_apify_sync(
                                        account,
                                        trigger=ApifyRefreshJobTrigger.BULK,
                                        parent_batch_id=apify_batch_id,
                                        batch_ctx=batch_scrape,
                                    )
                                except Exception as e:
                                    err_msg = str(e).replace("\r\n", " ").replace("\n", " ").strip()
                                    if len(err_msg) > 800:
                                        err_msg = err_msg[:797] + "..."
                                    _persist_auto_refresh_run_item(
                                        account.id,
                                        status="error",
                                        worker=None,
                                        detail=err_msg,
                                    )
                                    _mark_progress(success=False, failed=True, last_error=err_msg)
                                    errors_out.append({"id": account.id, "detail": err_msg})
                                else:
                                    job = (
                                        ApifyRefreshJob.objects.filter(account_id=account.id)
                                        .order_by("-id")
                                        .first()
                                    )
                                    if job and job.status != ApifyRefreshJobStatus.SUCCEEDED:
                                        err_msg = (job.error_message or "╨Ю╤И╨╕╨▒╨║╨░ Apify")[:800]
                                        _persist_auto_refresh_run_item(
                                            account.id,
                                            status="error",
                                            worker=None,
                                            detail=err_msg,
                                        )
                                        _mark_progress(
                                            success=False, failed=True, last_error=err_msg,
                                        )
                                        errors_out.append({"id": account.id, "detail": err_msg})
                                    else:
                                        _persist_auto_refresh_run_item(
                                            account.id, status="done", worker=None, detail="",
                                        )
                                        _mark_progress(success=True, failed=False)
                            else:
                                if is_refresh_cancel_requested():
                                    stop_requested.set()
                                    return
                                ensure_fresh_db_connections()
                                account = Account.objects.select_related("profile").get(pk=account.pk)
                                refresh_baseline = _account_refresh_baseline(account)
                                with _account_refresh_mutex(account.id):
                                    Account.objects.filter(pk=account.pk).update(
                                        profile_unavailable=False,
                                    )
                                    account.profile_unavailable = False
                                    key = _normalize_instagram_username_key(account.username)
                                    scraped = None
                                    if account.platform == Platform.INSTAGRAM and key in preload:
                                        scraped = preload[key]
                                    attempted_network = True
                                    refreshed, detail, _ = _refresh_account_for_api(
                                        account, scraped=scraped,
                                    )
                                if refreshed is not None and is_refresh_cancel_requested():
                                    _restore_account_refresh_baseline(account.pk, refresh_baseline)
                                    refreshed = None
                                    detail = "╨Ю╤Б╤В╨░╨╜╨╛╨▓╨╗╨╡╨╜╨╛ ╨┐╨╛╨╗╤М╨╖╨╛╨▓╨░╤В╨╡╨╗╨╡╨╝"
                                if refreshed is not None:
                                    _persist_auto_refresh_run_item(
                                        account.id, status="done", worker=None, detail="",
                                    )
                                    _mark_progress(success=True, failed=False)
                                elif detail and "╨Ю╤Б╤В╨░╨╜╨╛╨▓╨╗╨╡╨╜" in str(detail):
                                    _persist_auto_refresh_run_item(
                                        account.id,
                                        status="cancelled",
                                        worker=None,
                                        detail=str(detail)[:800],
                                    )
                                    _mark_progress(success=False, failed=False)
                                    stop_requested.set()
                                else:
                                    err_msg = str(detail or "")
                                    captcha_exc = ValueError(err_msg)
                                    batch_scrape.on_tiktok_playwright_error(
                                        account,
                                        captcha_exc,
                                    )
                                    apify_recovered = False
                                    if account.platform == Platform.TIKTOK:
                                        from accounts.tiktok_scrape_fallback import (
                                            retry_tiktok_via_apify_after_captcha,
                                        )

                                        try:
                                            apify_acc = retry_tiktok_via_apify_after_captcha(
                                                account,
                                                captcha_exc,
                                                batch_ctx=batch_scrape,
                                                trigger=ApifyRefreshJobTrigger.BULK,
                                                parent_batch_id=apify_batch_id,
                                            )
                                        except Exception as apify_exc:
                                            err_msg = str(apify_exc)
                                        else:
                                            if apify_acc is not None:
                                                _persist_auto_refresh_run_item(
                                                    account.id,
                                                    status="done",
                                                    worker=None,
                                                    detail="",
                                                )
                                                _mark_progress(success=True, failed=False)
                                                apify_recovered = True
                                    if not apify_recovered:
                                        _persist_auto_refresh_run_item(
                                            account.id,
                                            status="error",
                                            worker=None,
                                            detail=err_msg[:800],
                                        )
                                        _mark_progress(
                                            success=False, failed=True, last_error=err_msg
                                        )
                                        errors_out.append({"id": account.id, "detail": detail})
                        except RefreshCancelledError:
                            if attempted_network:
                                _restore_account_refresh_baseline(account.pk, refresh_baseline)
                            _persist_auto_refresh_run_item(
                                account.id,
                                status="cancelled",
                                worker=None,
                                detail="╨Ю╤Б╤В╨░╨╜╨╛╨▓╨╗╨╡╨╜╨╛ ╨┐╨╛╨╗╤М╨╖╨╛╨▓╨░╤В╨╡╨╗╨╡╨╝",
                            )
                            _mark_progress(success=False, failed=False)
                            stop_requested.set()
                        except Exception as e:
                            from accounts.scrape_fallback_recovery import (
                                apify_fallback_detail_suffix,
                                notify_playwright_batch_errors,
                                try_apify_recovery_after_playwright_failure,
                            )

                            refresh_failure_exc = e
                            notify_playwright_batch_errors(
                                account,
                                e,
                                batch_ctx=batch_scrape,
                                fb_batch_guard=fb_batch_guard,
                            )
                            apify_recovered = False
                            try:
                                apify_acc = try_apify_recovery_after_playwright_failure(
                                    account,
                                    e,
                                    batch_ctx=batch_scrape,
                                    trigger=ApifyRefreshJobTrigger.BULK,
                                    parent_batch_id=apify_batch_id,
                                )
                            except Exception as apify_exc:
                                e = apify_exc
                                refresh_failure_exc = apify_exc
                            else:
                                if apify_acc is not None:
                                    refresh_failure_exc = None
                                    _persist_auto_refresh_run_item(
                                        account.id,
                                        status="done",
                                        worker=None,
                                        detail=apify_fallback_detail_suffix(
                                            batch_scrape, account
                                        ),
                                    )
                                    _mark_progress(success=True, failed=False)
                                    apify_recovered = True
                            if not apify_recovered:
                                _mark_profile_unavailable_if_applicable(account, e)
                                detail = str(e).replace("\r\n", " ").replace("\n", " ").strip()
                                if len(detail) > 800:
                                    detail = detail[:797] + "..."
                                _persist_auto_refresh_run_item(
                                    account.id,
                                    status="error",
                                    worker=None,
                                    detail=detail,
                                )
                                _mark_progress(success=False, failed=True, last_error=detail)
                                errors_out.append({"id": account.id, "detail": detail})
                                print(
                                    f"[bulk_refresh] {account.platform}/@{account.username}: {e}",
                                    file=sys.stderr,
                                )
                        finally:
                            if attempted_network and not is_refresh_cancel_requested():
                                delay_sec = (
                                    0.0
                                    if should_use_apify_for_account(account, batch_ctx=batch_scrape)
                                    else _refresh_all_cooldown_seconds(
                                        account,
                                        refresh_failure_exc,
                                    )
                                )
                                if delay_sec > 0:
                                    account_queue.set_platform_cooldown(
                                        account.platform,
                                        delay_sec,
                                    )
                                if account.platform == Platform.FACEBOOK and delay_sec > 0:
                                    print(
                                        f"[bulk_refresh] facebook cooldown {delay_sec:.0f} ╤Б",
                                        file=sys.stderr,
                                        flush=True,
                                    )
                                warm_tracker.after_network_refresh(account.platform)
                            if stop_requested.is_set():
                                account_queue.abandon(idx, account.platform)
                            else:
                                account_queue.finish(idx, account.platform)

                with ThreadPoolExecutor(max_workers=worker_count) as executor:
                    futures = submit_refresh_workers(
                        executor,
                        _worker,
                        worker_count=worker_count,
                        has_facebook=has_fb_accounts,
                    )
                    for f in futures:
                        f.result()

                from .warm_run_detail import is_refresh_cancel_requested as _refresh_cancelled

                warm_tracker.join_warm_threads(
                    timeout=15.0 if _refresh_cancelled() else None,
                )

                with state_lock:
                    state.refresh_from_db()
                    if stop_requested.is_set():
                        _mark_bulk_refresh_queued_cancelled(state)
                    if errors_out:
                        last = errors_out[-1]
                        prefix = "╨Ю╤Б╤В╨░╨╜╨╛╨▓╨║╨░ ╨╖╨░╨┐╤А╨╛╤И╨╡╨╜╨░. " if stop_requested.is_set() else ""
                        state.last_error = (
                            f"{prefix}╨Ю╤И╨╕╨▒╨╛╨║: {len(errors_out)} ╨╕╨╖ {len(ordered)}. "
                            f"╨Я╨╛╤Б╨╗╨╡╨┤╨╜╤П╤П (id={last.get('id')}): {last.get('detail', '')}"
                        )[:4000]
                        state.save(update_fields=["last_error", "updated_at"])
                    elif not stop_requested.is_set():
                        state.last_error = ""
                        state.save(update_fields=["last_error", "updated_at"])
            finally:
                try:
                    from platforms.rumble.scraper import release_batch_resources

                    release_batch_resources()
                except Exception:
                    pass
                end_facebook_batch()
                leave_sync_apify_batch()
    finally:
        if warm_tracker is not None:
            try:
                warm_tracker.join_warm_threads()
            except Exception:
                pass
        finished = timezone.now()
        state.refresh_from_db()
        if stop_requested.is_set():
            _mark_bulk_refresh_queued_cancelled(state)
        state.is_running = False
        state.cancel_requested = False
        state.current_account = ""
        state.finished_at = finished
        state.save(update_fields=[
            "is_running", "cancel_requested", "current_account",
            "finished_at", "run_detail", "updated_at",
        ])


def _schedule_skip_recent_cutoff() -> tuple[int, datetime.datetime | None]:
    from .refresh_skip_recent import schedule_skip_recent_cutoff

    return schedule_skip_recent_cutoff()


def _persist_auto_refresh_run_item(account_id: int, **kwargs) -> None:
    from .run_detail_items import merge_run_detail_item

    try:
        with transaction.atomic():
            st = AutoRefreshState.objects.select_for_update().get(pk=1)
            rd = dict(st.run_detail or {})
            items = [dict(x) for x in (rd.get("items") or [])]
            aid = int(account_id)
            for i, it in enumerate(items):
                if int(it.get("account_id", -1)) != aid:
                    continue
                items[i] = merge_run_detail_item(it, kwargs)
                break
            rd["items"] = items
            st.run_detail = rd
            st.save(update_fields=["run_detail", "updated_at"])
    except Exception as e:
        logger.warning(
            "auto_refresh.run_detail_update_failed",
            extra={"account_id": account_id, "error": str(e)},
        )


def _persist_refresh_all_run_item(account_id: int, **kwargs) -> None:
    from .run_detail_items import merge_run_detail_item

    try:
        with transaction.atomic():
            st = RefreshAllState.objects.select_for_update().get(pk=1)
            rd = dict(st.run_detail or {})
            items = [dict(x) for x in (rd.get("items") or [])]
            aid = int(account_id)
            for i, it in enumerate(items):
                if int(it.get("account_id", -1)) != aid:
                    continue
                items[i] = merge_run_detail_item(it, kwargs)
                break
            rd["items"] = items
            st.run_detail = rd
            st.save(update_fields=["run_detail", "updated_at"])
    except Exception as e:
        logger.warning("refresh_all.run_detail_update_failed", extra={"account_id": account_id, "error": str(e)})


def _finalize_refresh_all_run_detail_stale() -> None:
    try:
        with transaction.atomic():
            st = RefreshAllState.objects.select_for_update().get(pk=1)
            rd = dict(st.run_detail or {})
            items = [dict(x) for x in (rd.get("items") or [])]
            changed = False
            for it in items:
                stt = str(it.get("status") or "")
                if stt in ("queued", "running"):
                    it["status"] = "cancelled"
                    it["detail"] = "╨╜╨╡ ╨╛╨▒╤А╨░╨▒╨╛╤В╨░╨╜ (╨╛╤Б╤В╨░╨╜╨╛╨▓╨║╨░ ╨╕╨╗╨╕ ╨┐╤А╨╡╤А╤Л╨▓╨░╨╜╨╕╨╡)"
                    it["worker"] = None
                    changed = True
            if changed:
                rd["items"] = items
                st.run_detail = rd
                st.save(update_fields=["run_detail", "updated_at"])
    except Exception as e:
        logger.warning("refresh_all.run_detail_finalize_failed", extra={"error": str(e)})


def _refresh_all_cancel_requested() -> bool:
    try:
        v = RefreshAllState.objects.filter(pk=1).values_list("cancel_requested", flat=True).first()
        return bool(v)
    except Exception:
        return False


def _refresh_all_set_user_stop_message() -> None:
    RefreshAllState.objects.filter(pk=1).update(
        last_error="╨б╨▒╨╛╤А ╨╛╤Б╤В╨░╨╜╨╛╨▓╨╗╨╡╨╜ ╨┐╨╛╨╗╤М╨╖╨╛╨▓╨░╤В╨╡╨╗╨╡╨╝.",
        updated_at=timezone.now(),
    )


def _refresh_all_atomic_progress(*, failed: bool, last_error: str = "") -> None:
    """╨Я╨╛╤В╨╛╨║╨╛╨▒╨╡╨╖╨╛╨┐╨░╤Б╨╜╤Л╨╣ ╤Б╤З╤С╤В╤З╨╕╨║ ╨┐╤А╨╛╨│╤А╨╡╤Б╤Б╨░ ╨▒╨╡╨╖ ╨╛╨▒╤Й╨╡╨│╨╛ ╤Н╨║╨╖╨╡╨╝╨┐╨╗╤П╤А╨░ ╨╝╨╛╨┤╨╡╨╗╨╕ ╨▓ ╨┐╨░╨╝╤П╤В╨╕."""
    now = timezone.now()
    qs = RefreshAllState.objects.filter(pk=1)
    if failed:
        qs.update(
            processed_accounts=F("processed_accounts") + 1,
            failed_accounts=F("failed_accounts") + 1,
            last_error=(last_error or "")[:4000],
            updated_at=now,
        )
    else:
        qs.update(
            processed_accounts=F("processed_accounts") + 1,
            success_accounts=F("success_accounts") + 1,
            updated_at=now,
        )


def _refresh_all_apply_completion_summary(report_rows: list[dict]) -> None:
    """
    ╨Я╨╛╤Б╨╗╨╡ ╨┐╨╛╨╗╨╜╨╛╨│╨╛ ╨┐╤А╨╛╤Е╨╛╨┤╨░ ╨╛╤З╨╡╤А╨╡╨┤╨╕: ╨╖╨░╤Д╨╕╨║╤Б╨╕╤А╨╛╨▓╨░╤В╤М ╤Б╨▓╨╛╨┤╨║╤Г ╨┐╨╛ ╨╛╤И╨╕╨▒╨║╨░╨╝ ╨▓ last_error ╨╕ run_detail.
    ╨Т╨╛ ╨▓╤А╨╡╨╝╤П ╨┐╤А╨╛╨│╨╛╨╜╨░ last_error ╨┐╨╡╤А╨╡╨╖╨░╨┐╨╕╤Б╤Л╨▓╨░╨╡╤В╤Б╤П ╨┐╨╛╤Б╨╗╨╡╨┤╨╜╨╡╨╣ ╨╛╤И╨╕╨▒╨║╨╛╨╣ ╨┐╨╛ ╨░╨║╨║╨░╤Г╨╜╤В╤Г тАФ ╨╖╨┤╨╡╤Б╤М ╨┤╨░╤С╨╝ ╨╕╤В╨╛╨│.
    """
    try:
        with transaction.atomic():
            st = RefreshAllState.objects.select_for_update().get(pk=1)
            rd = st.run_detail if isinstance(st.run_detail, dict) else {}
            rd = dict(rd)
            err_rows = [r for r in report_rows if r.get("status") == "╨╛╤И╨╕╨▒╨║╨░"]
            failed_n = len(err_rows)
            if failed_n:
                last = err_rows[-1]
                uname = str(last.get("username") or "")
                plat = str(last.get("platform") or "")
                err_txt = str(last.get("error") or "")
                rd["completion_summary"] = {
                    "failed_count": failed_n,
                    "last_username": uname,
                    "last_platform": plat,
                    "last_error_detail": err_txt[:2000],
                }
                summary_msg = (
                    f"╨Т ╤Е╨╛╨┤╨╡ ╤Б╨▒╨╛╤А╨░ ╨╛╤И╨╕╨▒╨╛╨║: {failed_n}. "
                    f"╨Я╨╛╤Б╨╗╨╡╨┤╨╜╤П╤П ({plat}/@{uname}): {err_txt}"
                )[:4000]
                st.run_detail = rd
                st.last_error = summary_msg
                st.save(update_fields=["run_detail", "last_error", "updated_at"])
            else:
                rd.pop("completion_summary", None)
                st.run_detail = rd
                st.last_error = ""
                st.save(update_fields=["run_detail", "last_error", "updated_at"])
    except Exception as e:
        logger.warning("refresh_all.completion_summary_failed", extra={"error": str(e)})


def _refresh_all_local_dt_str(dt) -> str:
    """╨з╨╡╨╗╨╛╨▓╨╡╨║╨╛╤З╨╕╤В╨░╨╡╨╝╨╛╨╡ ╨╗╨╛╨║╨░╨╗╤М╨╜╨╛╨╡ ╨▓╤А╨╡╨╝╤П (╨╜╨░╤Б╤В╤А╨╛╨╣╨║╨╕ Django, ╨╛╨▒╤Л╤З╨╜╨╛ Europe/Moscow)."""
    if not dt:
        return ""
    if timezone.is_naive(dt):
        dt = timezone.make_aware(dt, timezone.get_current_timezone())
    return timezone.localtime(dt).strftime("%d.%m.%Y %H:%M:%S")


def _refresh_all_save_report_csv(
    *,
    report_rows: list[dict],
    run_wall_start,
    run_wall_end,
    run_duration_mono_sec: float,
    worker_count: int,
    processed_db: int,
    success_db: int,
    failed_db: int,
) -> None:
    """
    ╨б╨╛╤Е╤А╨░╨╜╤П╨╡╤В UTF-8 CSV ╨╛╤В╤З╤С╤В╨░ ╨┐╨╛╤Б╨╗╨╡╨┤╨╜╨╡╨│╨╛ ┬л╤Б╨╛╨▒╤А╨░╤В╤М ╨▓╤Б╨╡╤Е┬╗ ╨▓ RefreshAllState.last_report_csv
    ╨╕ ╨╝╨╡╤В╨░╨┤╨░╨╜╨╜╤Л╨╡ ╨┐╤А╨╛╨│╨╛╨╜╨░ ╨▓ run_detail['report_run'].
    """
    try:
        wall_sec = 0.0
        if run_wall_start and run_wall_end:
            wall_sec = max(0.0, (run_wall_end - run_wall_start).total_seconds())
        buffer = io.StringIO()
        writer = csv.writer(buffer, lineterminator="\n")
        headers = [
            "ID ╨░╨║╨║╨░╤Г╨╜╤В╨░",
            "╨Я╨╗╨╛╤Й╨░╨┤╨║╨░",
            "╨Ы╨╛╨│╨╕╨╜",
            "╨б╤В╨░╤В╤Г╤Б",
            "╨б╨╡╨║╤Г╨╜╨┤ ╨╜╨░ ╨╛╨▒╨╜╨╛╨▓╨╗╨╡╨╜╨╕╨╡",
            "╨Э╨░╤З╨░╨╗╨╛ ╨╛╨▒╨╜╨╛╨▓╨╗╨╡╨╜╨╕╤П (╨╗╨╛╨║╨░╨╗╤М╨╜╨╛╨╡)",
            "╨Ъ╨╛╨╜╨╡╤Ж ╨╛╨▒╨╜╨╛╨▓╨╗╨╡╨╜╨╕╤П (╨╗╨╛╨║╨░╨╗╤М╨╜╨╛╨╡)",
            "╨б╨╛╤Е╤А╨░╨╜╨╡╨╜╨╛ ╨▓ ╨С╨Ф (╨╗╨╛╨║╨░╨╗╤М╨╜╨╛╨╡)",
            "╨Я╨╛╨┤╨┐╨╕╤Б╤З╨╕╨║╨╕",
            "╨Ф╨╡╨╗╤М╤В╨░ ╨┐╨╛╨┤╨┐╨╕╤Б╤З╨╕╨║╨╛╨▓",
            "╨Ы╨░╨╣╨║╨╕",
            "╨Ф╨╡╨╗╤М╤В╨░ ╨╗╨░╨╣╨║╨╛╨▓",
            "╨Я╤А╨╛╤Б╨╝╨╛╤В╤А╤Л",
            "╨Ф╨╡╨╗╤М╤В╨░ ╨┐╤А╨╛╤Б╨╝╨╛╤В╤А╨╛╨▓",
            "╨Я╨╛╤Б╤В╤Л",
            "╨Ф╨╡╨╗╤М╤В╨░ ╨┐╨╛╤Б╤В╨╛╨▓",
            "╨в╨╡╨║╤Б╤В ╨╛╤И╨╕╨▒╨║╨╕",
        ]
        writer.writerow(headers)
        for row in report_rows:
            writer.writerow([
                row.get("id", ""),
                row.get("platform", ""),
                row.get("username", ""),
                row.get("status", ""),
                row.get("refresh_duration_sec", ""),
                row.get("refresh_started_local", ""),
                row.get("refresh_finished_local", ""),
                row.get("account_db_updated_local", ""),
                row.get("follower_count", ""),
                row.get("follower_delta", ""),
                row.get("like_count", ""),
                row.get("like_delta", ""),
                row.get("view_count", ""),
                row.get("view_delta", ""),
                row.get("post_count", ""),
                row.get("post_delta", ""),
                row.get("error", ""),
            ])
        writer.writerow([])
        writer.writerow(["╨Ш╨в╨Ю╨У ╨┐╤А╨╛╨│╨╛╨╜╨░", "╨Я╨░╤А╨░╨╝╨╡╤В╤А", "╨Ч╨╜╨░╤З╨╡╨╜╨╕╨╡"])
        ok_rows = sum(
            1 for r in report_rows
            if r.get("status") in ("╨╛╨▒╨╜╨╛╨▓╨╕╨╗╨╛╤Б╤М", "╨╜╨╡╤В ╨╛╨▒╨╜╨╛╨▓╨╗╨╡╨╜╨╕╨╣")
        )
        meta_lines = [
            ("╨Э╨░╤З╨░╨╗╨╛ ╤Б╨▒╨╛╤А╨░ (╨╗╨╛╨║╨░╨╗╤М╨╜╨╛╨╡)", _refresh_all_local_dt_str(run_wall_start)),
            ("╨Ъ╨╛╨╜╨╡╤Ж ╤Б╨▒╨╛╤А╨░ (╨╗╨╛╨║╨░╨╗╤М╨╜╨╛╨╡)", _refresh_all_local_dt_str(run_wall_end)),
            ("╨Т╤Б╨╡╨│╨╛ ╤Б╨╡╨║╤Г╨╜╨┤ (╨╝╨╛╨╜╨╛╤В╨╛╨╜╨╜╨╛)", str(round(run_duration_mono_sec, 3))),
            ("╨Т╤Б╨╡╨│╨╛ ╤Б╨╡╨║╤Г╨╜╨┤ (╨┐╨╛ ╤З╨░╤Б╨░╨╝)", str(round(wall_sec, 3))),
            ("╨Т╨╛╤А╨║╨╡╤А╨╛╨▓", str(worker_count)),
            ("╨б╤В╤А╨╛╨║ ╨▓ ╨╛╤В╤З╤С╤В╨╡", str(len(report_rows))),
            ("╨г╤Б╨┐╨╡╤И╨╜╤Л╤Е (╨┐╨╛ ╤Б╤В╤А╨╛╨║╨░╨╝)", str(ok_rows)),
            ("╨Ю╤И╨╕╨▒╨╛╨║ (╨┐╨╛ ╤Б╤В╤А╨╛╨║╨░╨╝)", str(sum(1 for r in report_rows if r.get("status") == "╨╛╤И╨╕╨▒╨║╨░"))),
            ("╨Э╨╡ ╨▓╤Л╨┐╨╛╨╗╨╜╨╡╨╜╨╛ (╨┐╨╛ ╤Б╤В╤А╨╛╨║╨░╨╝)", str(sum(1 for r in report_rows if r.get("status") == "╨╜╨╡ ╨▓╤Л╨┐╨╛╨╗╨╜╨╡╨╜╨╛"))),
            ("╨Ю╨▒╤А╨░╨▒╨╛╤В╨░╨╜╨╛ (╤Б╤З╤С╤В╤З╨╕╨║ ╨С╨Ф)", str(processed_db)),
            ("╨г╤Б╨┐╨╡╤И╨╜╨╛ (╤Б╤З╤С╤В╤З╨╕╨║ ╨С╨Ф)", str(success_db)),
            ("╨б ╨╛╤И╨╕╨▒╨║╨╛╨╣ (╤Б╤З╤С╤В╤З╨╕╨║ ╨С╨Ф)", str(failed_db)),
        ]
        for label, value in meta_lines:
            writer.writerow(["╨Ш╨в╨Ю╨У ╨┐╤А╨╛╨│╨╛╨╜╨░", label, value])

        generated_at = timezone.now()
        meta_dict = {
            "generated_at": generated_at.isoformat(),
            "run_started_local": _refresh_all_local_dt_str(run_wall_start),
            "run_finished_local": _refresh_all_local_dt_str(run_wall_end),
            "total_duration_mono_sec": round(run_duration_mono_sec, 4),
            "total_duration_wall_sec": round(wall_sec, 4),
            "worker_count": worker_count,
            "row_count": len(report_rows),
            "row_ok_count": ok_rows,
            "row_error_count": sum(1 for r in report_rows if r.get("status") == "╨╛╤И╨╕╨▒╨║╨░"),
            "row_skipped_count": sum(1 for r in report_rows if r.get("status") == "╨╜╨╡ ╨▓╤Л╨┐╨╛╨╗╨╜╨╡╨╜╨╛"),
            "db_processed_accounts": processed_db,
            "db_success_accounts": success_db,
            "db_failed_accounts": failed_db,
        }
        with transaction.atomic():
            st = RefreshAllState.objects.select_for_update().get(pk=1)
            rd = dict(st.run_detail) if isinstance(st.run_detail, dict) else {}
            rd["report_run"] = meta_dict
            st.run_detail = rd
            st.last_report_csv = buffer.getvalue()
            st.last_report_generated_at = generated_at
            st.save(update_fields=["run_detail", "last_report_csv", "last_report_generated_at", "updated_at"])
    except Exception as e:
        logger.warning("refresh_all.save_report_csv_failed", extra={"error": str(e)})


def _run_refresh_all_background(
    *,
    include_hidden_platforms: bool,
    include_hidden_profiles: bool,
    include_archived_accounts: bool,
    include_banned_accounts: bool,
    download_csv: bool,
) -> None:
    import uuid

    from .refresh_cancel import RefreshCancelledError
    from django.db import close_old_connections

    close_old_connections()
    state = RefreshAllState.get()
    apify_batch_id = uuid.uuid4()

    _prev_worker_autoclose = os.environ.get("WORKER_AUTOCLOSE_BROWSER_ON_EXIT")
    os.environ["WORKER_AUTOCLOSE_BROWSER_ON_EXIT"] = "1"
    try:
        from .refresh_queue import order_accounts_for_refresh, queryset_order_by_staleness

        accounts_qs = queryset_order_by_staleness(Account.objects.all())
        if not include_archived_accounts:
            accounts_qs = accounts_qs.filter(is_archived=False)
        if not include_banned_accounts:
            accounts_qs = accounts_qs.filter(is_banned=False)
        accounts_qs = _apply_visibility_filters(
            accounts_qs,
            include_hidden_platforms=include_hidden_platforms,
            include_hidden_profiles=include_hidden_profiles,
        )
        accounts = order_accounts_for_refresh(list(accounts_qs))
        worker_count = _parallel_refresh_worker_count(accounts)
        _ = download_csv  # CSV ╨╜╨░ ╤Б╨╡╤А╨▓╨╡╤А╨╡ ╨▓╤Б╨╡╨│╨┤╨░; ╤Д╨╗╨░╨│ ╤В╨╛╨╗╤М╨║╨╛ ╨▓ ╨╛╤В╨▓╨╡╤В╨╡ POST ╨┤╨╗╤П ╤Б╨╛╨▓╨╝╨╡╤Б╤В╨╕╨╝╨╛╤Б╤В╨╕

        skip_recent_hours, skip_cutoff = _schedule_skip_recent_cutoff()
        from .refresh_skip_recent import build_initial_run_detail_items

        run_items, skip_initial = build_initial_run_detail_items(
            accounts,
            skip_recent_hours=skip_recent_hours,
            cutoff=skip_cutoff,
        )
        state.total_accounts = len(accounts)
        state.processed_accounts = skip_initial
        state.success_accounts = skip_initial
        state.failed_accounts = 0
        state.run_detail = {
            "items": run_items,
            "worker_count": worker_count,
            "apify_batch_id": str(apify_batch_id),
        }
        state.save(update_fields=[
            "total_accounts", "processed_accounts", "success_accounts", "failed_accounts",
            "run_detail", "updated_at",
        ])

        if not accounts:
            return

        try:
            from platforms.apify.abort import abort_active_apify_jobs

            aborted = abort_active_apify_jobs()
            if aborted:
                print(
                    f"[refresh_all] ╨╛╤В╨╝╨╡╨╜╨╡╨╜╨╛ ╨░╨║╤В╨╕╨▓╨╜╤Л╤Е Apify jobs: {aborted}",
                    file=sys.stderr,
                    flush=True,
                )
        except Exception as exc:
            print(f"[refresh_all] abort Apify jobs failed: {exc}", file=sys.stderr)
        from platforms.apify.batch_guard import enter_sync_apify_batch, leave_sync_apify_batch

        enter_sync_apify_batch(apify_batch_id)
        from .facebook_refresh_lane import (
            begin_facebook_batch,
            end_facebook_batch,
            batch_has_facebook,
            platform_claim_filter,
            submit_refresh_workers,
            try_mark_facebook_account_started,
            allocate_worker_slot,
            ensure_facebook_playwright_daemon_ready,
            filter_accounts_for_playwright_prewarm,
        )

        has_fb_accounts = batch_has_facebook(accounts)
        begin_facebook_batch()

        skip_recent_hours, cutoff = _schedule_skip_recent_cutoff()

        ig_preload: dict[str, dict] = {}

        from .scrape_backend import (
            accounts_needing_playwright,
            facebook_playwright_warm_needed,
            refresh_account_via_apify_sync,
            should_use_apify_for_account,
        )
        from accounts.models import ApifyRefreshJob, ApifyRefreshJobStatus, ApifyRefreshJobTrigger

        has_facebook = facebook_playwright_warm_needed(accounts)
        from .scrape_backend import BatchScrapeContext

        batch_scrape = BatchScrapeContext.for_accounts(accounts)
        fb_batch_guard = None
        if has_facebook:
            from platforms.facebook.rate_limit import FacebookRefreshBatchGuard

            fb_fb = batch_scrape.facebook_fallback
            if fb_fb is None or not fb_fb.enabled:
                fb_batch_guard = FacebookRefreshBatchGuard()

        from .refresh_priority import account_refresh_priority_session

        with account_refresh_priority_session():
            try:
                from integrations.links_sync import begin_refresh_all_links, clear_refresh_all_links

                begin_refresh_all_links(accounts)
            except Exception as e:
                print(f"[refresh_all] links preload failed: {e}", file=sys.stderr)

            from django.conf import settings as dj_settings

            pw_accounts = filter_accounts_for_playwright_prewarm(
                accounts_needing_playwright(accounts),
            )
            try:
                from platforms.rumble.scraper import release_batch_resources, skip_playwright_prewarm

                if skip_playwright_prewarm():
                    release_batch_resources()
            except Exception:
                pass
            if pw_accounts and bool(
                getattr(dj_settings, "ACCOUNTS_AUTOREFRESH_PREWARM_PLAYWRIGHT", False),
            ):
                _prewarm_workers(pw_accounts)

            from .parallel_account_queue import ParallelAccountQueue
            from .refresh_all_warm import RefreshAllWarmTracker

            report_lock = threading.Lock()
            stop_requested = threading.Event()
            _fb_daemon_prepared = threading.Event()

            warm_tracker = RefreshAllWarmTracker(accounts, label="refresh_all")
            if _refresh_all_cancel_requested():
                stop_requested.set()
            report_by_index: list[dict | None] = [None] * len(accounts)
            platform_limits = _refresh_platform_limits(accounts)
            account_queue = ParallelAccountQueue(len(accounts), platform_limits)
            from .refresh_skip_recent import apply_upfront_skip_recent

            apply_upfront_skip_recent(
                accounts,
                cutoff=cutoff,
                skip_recent_hours=skip_recent_hours,
                account_queue=account_queue,
            )

            thread_slot_map: dict[int, int] = {}
            thread_slot_lock = threading.Lock()

            def _worker_slot(*, facebook_lane: bool) -> int:
                return allocate_worker_slot(
                    facebook_lane=facebook_lane,
                    thread_slot_map=thread_slot_map,
                    thread_slot_lock=thread_slot_lock,
                )

            def _worker(facebook_lane: bool) -> None:
                if facebook_lane and not _fb_daemon_prepared.is_set():
                    try:
                        ensure_facebook_playwright_daemon_ready()
                    except Exception as exc:
                        print(
                            f"[refresh_all] Facebook daemon: {exc}",
                            file=sys.stderr,
                            flush=True,
                        )
                    _fb_daemon_prepared.set()
                while True:
                    if stop_requested.is_set():
                        return
                    if _refresh_all_cancel_requested():
                        _refresh_all_set_user_stop_message()
                        stop_requested.set()
                        return
                    idx = account_queue.claim(
                        lambda i: accounts[i].platform,
                        stop_event=stop_requested,
                        platform_filter=platform_claim_filter(facebook_lane=facebook_lane),
                    )
                    if idx is None:
                        return
                    close_old_connections()
                    account = accounts[idx]
                    if (
                        facebook_lane
                        and account.platform == Platform.FACEBOOK
                        and not try_mark_facebook_account_started(account.id)
                    ):
                        account_queue.abandon(idx, account.platform)
                        continue
                    from .warm_run_detail import is_refresh_cancel_requested

                    if is_refresh_cancel_requested():
                        stop_requested.set()
                        return
                    release_db_for_long_task()
                    warm_tracker.wait_warm_before_refresh(account.platform)
                    if is_refresh_cancel_requested():
                        stop_requested.set()
                        return
                    before = {
                        "follower_count": account.follower_count,
                        "like_count": account.like_count,
                        "view_count": account.view_count,
                        "post_count": account.post_count,
                    }
                    row: dict | None = None
                    attempted_network = False
                    refresh_failure_exc: BaseException | None = None
                    refresh_baseline: dict | None = None
                    try:
                        if stop_requested.is_set():
                            return
                        if _refresh_all_cancel_requested():
                            _refresh_all_set_user_stop_message()
                            stop_requested.set()
                            return

                        slot = _worker_slot(facebook_lane=facebook_lane)
                        RefreshAllState.objects.filter(pk=1).update(
                            current_account=f"{account.platform}/@{account.username}",
                            updated_at=timezone.now(),
                        )
                        _persist_refresh_all_run_item(account.id, status="running", worker=slot)

                        acc_mono_start = time.monotonic()
                        acc_wall_start = timezone.now()
                        try:
                            if (
                                cutoff is not None
                                and account.updated_at
                                and account.updated_at >= cutoff
                            ):
                                account.refresh_from_db(
                                    fields=[
                                        "follower_count",
                                        "like_count",
                                        "view_count",
                                        "post_count",
                                        "updated_at",
                                    ],
                                )
                                skip_detail = f"╨╜╨╡╨┤╨░╨▓╨╜╨╛ ╨╛╨▒╨╜╨╛╨▓╨╗╤С╨╜ (тЙд {skip_recent_hours} ╤З)"
                                row = {
                                    "id": account.id,
                                    "platform": account.platform,
                                    "username": account.username,
                                    "status": "╨┐╤А╨╛╨┐╤Г╤Й╨╡╨╜",
                                    "follower_count": account.follower_count,
                                    "follower_delta": 0,
                                    "like_count": account.like_count,
                                    "like_delta": 0,
                                    "view_count": account.view_count,
                                    "view_delta": 0,
                                    "post_count": account.post_count,
                                    "post_delta": 0,
                                    "detail": skip_detail,
                                }
                                _refresh_all_atomic_progress(failed=False)
                                _persist_refresh_all_run_item(
                                    account.id,
                                    status="skipped",
                                    worker=None,
                                    detail=skip_detail,
                                )
                            elif (
                                account.platform == Platform.FACEBOOK
                                and fb_batch_guard is not None
                                and not should_use_apify_for_account(account, batch_ctx=batch_scrape)
                                and fb_batch_guard.is_tripped()
                            ):
                                skip_detail = fb_batch_guard.skip_detail()
                                row = {
                                    "id": account.id,
                                    "platform": account.platform,
                                    "username": account.username,
                                    "status": "╨┐╤А╨╛╨┐╤Г╤Й╨╡╨╜",
                                    "follower_count": before["follower_count"],
                                    "follower_delta": 0,
                                    "like_count": before["like_count"],
                                    "like_delta": 0,
                                    "view_count": before["view_count"],
                                    "view_delta": 0,
                                    "post_count": before["post_count"],
                                    "post_delta": 0,
                                    "detail": skip_detail,
                                }
                                _refresh_all_atomic_progress(failed=False)
                                _persist_refresh_all_run_item(
                                    account.id,
                                    status="skipped",
                                    worker=None,
                                    detail=skip_detail,
                                )
                            elif (
                                account.platform == Platform.TIKTOK
                                and batch_scrape.tiktok_captcha_tripped()
                                and not should_use_apify_for_account(account, batch_ctx=batch_scrape)
                            ):
                                err_detail = batch_scrape.tiktok_captcha_skip_detail()
                                row = {
                                    "id": account.id,
                                    "platform": account.platform,
                                    "username": account.username,
                                    "status": "╨╛╤И╨╕╨▒╨║╨░",
                                    "error": err_detail,
                                    "follower_count": before["follower_count"],
                                    "follower_delta": None,
                                    "like_count": before["like_count"],
                                    "like_delta": None,
                                    "view_count": before["view_count"],
                                    "view_delta": None,
                                    "post_count": before["post_count"],
                                    "post_delta": None,
                                }
                                _refresh_all_atomic_progress(failed=True, last_error=err_detail)
                                _persist_refresh_all_run_item(
                                    account.id,
                                    status="error",
                                    worker=None,
                                    detail=err_detail,
                                )
                            elif should_use_apify_for_account(account, batch_ctx=batch_scrape):
                                attempted_network = True
                                try:
                                    refresh_account_via_apify_sync(
                                        account,
                                        trigger=ApifyRefreshJobTrigger.REFRESH_ALL,
                                        parent_batch_id=apify_batch_id,
                                        batch_ctx=batch_scrape,
                                    )
                                except Exception as e:
                                    detail, _ = _format_refresh_error(account, e)
                                    row = {
                                        "id": account.id,
                                        "platform": account.platform,
                                        "username": account.username,
                                        "status": "╨╛╤И╨╕╨▒╨║╨░",
                                        "error": detail,
                                        "follower_count": before["follower_count"],
                                        "follower_delta": None,
                                        "like_count": before["like_count"],
                                        "like_delta": None,
                                        "view_count": before["view_count"],
                                        "view_delta": None,
                                        "post_count": before["post_count"],
                                        "post_delta": None,
                                    }
                                    _refresh_all_atomic_progress(
                                        failed=True, last_error=str(detail or "")
                                    )
                                    _persist_refresh_all_run_item(
                                        account.id,
                                        status="error",
                                        worker=None,
                                        detail=str(detail or "")[:800],
                                    )
                                else:
                                    job = (
                                        ApifyRefreshJob.objects.filter(account_id=account.id)
                                        .order_by("-id")
                                        .first()
                                    )
                                    account.refresh_from_db(
                                        fields=[
                                            "follower_count",
                                            "like_count",
                                            "view_count",
                                            "post_count",
                                            "link_click_count",
                                            "updated_at",
                                        ],
                                    )
                                    after = {
                                        "follower_count": account.follower_count,
                                        "like_count": account.like_count,
                                        "view_count": account.view_count,
                                        "post_count": account.post_count,
                                    }
                                    if job and job.status != ApifyRefreshJobStatus.SUCCEEDED:
                                        detail = (job.error_message or "╨Ю╤И╨╕╨▒╨║╨░ Apify")[:800]
                                        row = {
                                            "id": account.id,
                                            "platform": account.platform,
                                            "username": account.username,
                                            "status": "╨╛╤И╨╕╨▒╨║╨░",
                                            "error": detail,
                                            "follower_count": before["follower_count"],
                                            "follower_delta": None,
                                            "like_count": before["like_count"],
                                            "like_delta": None,
                                            "view_count": before["view_count"],
                                            "view_delta": None,
                                            "post_count": before["post_count"],
                                            "post_delta": None,
                                        }
                                        _refresh_all_atomic_progress(
                                            failed=True, last_error=detail,
                                        )
                                        _persist_refresh_all_run_item(
                                            account.id,
                                            status="error",
                                            worker=None,
                                            detail=detail,
                                        )
                                    else:
                                        changed = {
                                            k: (after[k] != before[k]) for k in before
                                        }
                                        changed_count = sum(1 for v in changed.values() if v)
                                        status_label = (
                                            "╨╜╨╡╤В ╨╛╨▒╨╜╨╛╨▓╨╗╨╡╨╜╨╕╨╣"
                                            if changed_count == 0
                                            else "╨╛╨▒╨╜╨╛╨▓╨╕╨╗╨╛╤Б╤М"
                                        )
                                        row = {
                                            "id": account.id,
                                            "platform": account.platform,
                                            "username": account.username,
                                            "status": status_label,
                                            "follower_count": after["follower_count"],
                                            "follower_delta": after["follower_count"]
                                            - before["follower_count"],
                                            "like_count": after["like_count"],
                                            "like_delta": after["like_count"]
                                            - before["like_count"],
                                            "view_count": after["view_count"],
                                            "view_delta": after["view_count"]
                                            - before["view_count"],
                                            "post_count": after["post_count"],
                                            "post_delta": after["post_count"]
                                            - before["post_count"],
                                        }
                                        _refresh_all_atomic_progress(failed=False)
                                        _persist_refresh_all_run_item(
                                            account.id,
                                            status="done",
                                            worker=None,
                                            detail="",
                                        )
                            else:
                                if is_refresh_cancel_requested():
                                    stop_requested.set()
                                    return
                                scraped = None
                                if account.platform == Platform.INSTAGRAM and ig_preload:
                                    key = (account.username or "").lstrip("@").strip().lower()
                                    scraped = ig_preload.get(key)
                                attempted_network = True
                                refresh_baseline = _account_refresh_baseline(account)
                                with _account_refresh_mutex(account.id):
                                    _refresh_with_retry(account, scraped=scraped)
                                if is_refresh_cancel_requested():
                                    _restore_account_refresh_baseline(account.pk, refresh_baseline)
                                    row = {
                                        "id": account.id,
                                        "platform": account.platform,
                                        "username": account.username,
                                        "status": "╨╛╤В╨╝╨╡╨╜╤С╨╜",
                                        "follower_count": before["follower_count"],
                                        "follower_delta": 0,
                                        "like_count": before["like_count"],
                                        "like_delta": 0,
                                        "view_count": before["view_count"],
                                        "view_delta": 0,
                                        "post_count": before["post_count"],
                                        "post_delta": 0,
                                        "detail": "╨Ю╤Б╤В╨░╨╜╨╛╨▓╨╗╨╡╨╜╨╛ ╨┐╨╛╨╗╤М╨╖╨╛╨▓╨░╤В╨╡╨╗╨╡╨╝",
                                    }
                                    _refresh_all_atomic_progress(failed=False)
                                    _persist_refresh_all_run_item(
                                        account.id,
                                        status="cancelled",
                                        worker=None,
                                        detail="╨Ю╤Б╤В╨░╨╜╨╛╨▓╨╗╨╡╨╜╨╛ ╨┐╨╛╨╗╤М╨╖╨╛╨▓╨░╤В╨╡╨╗╨╡╨╝",
                                    )
                                    stop_requested.set()
                                else:
                                    account.refresh_from_db(
                                        fields=[
                                            "follower_count",
                                            "like_count",
                                            "view_count",
                                            "post_count",
                                            "link_click_count",
                                            "updated_at",
                                        ],
                                    )
                                    after = {
                                        "follower_count": account.follower_count,
                                        "like_count": account.like_count,
                                        "view_count": account.view_count,
                                        "post_count": account.post_count,
                                    }
                                    changed = {k: (after[k] != before[k]) for k in before}
                                    changed_count = sum(1 for v in changed.values() if v)
                                    status_label = "╨╜╨╡╤В ╨╛╨▒╨╜╨╛╨▓╨╗╨╡╨╜╨╕╨╣" if changed_count == 0 else "╨╛╨▒╨╜╨╛╨▓╨╕╨╗╨╛╤Б╤М"
                                    row = {
                                        "id": account.id,
                                        "platform": account.platform,
                                        "username": account.username,
                                        "status": status_label,
                                        "follower_count": after["follower_count"],
                                        "follower_delta": after["follower_count"] - before["follower_count"],
                                        "like_count": after["like_count"],
                                        "like_delta": after["like_count"] - before["like_count"],
                                        "view_count": after["view_count"],
                                        "view_delta": after["view_count"] - before["view_count"],
                                        "post_count": after["post_count"],
                                        "post_delta": after["post_count"] - before["post_count"],
                                    }
                                    _refresh_all_atomic_progress(failed=False)
                                    _persist_refresh_all_run_item(account.id, status="done", worker=None, detail="")
                        except RefreshCancelledError:
                            _restore_account_refresh_baseline(account.pk, refresh_baseline)
                            row = {
                                "id": account.id,
                                "platform": account.platform,
                                "username": account.username,
                                "status": "╨╛╤В╨╝╨╡╨╜╤С╨╜",
                                "follower_count": before["follower_count"],
                                "follower_delta": 0,
                                "like_count": before["like_count"],
                                "like_delta": 0,
                                "view_count": before["view_count"],
                                "view_delta": 0,
                                "post_count": before["post_count"],
                                "post_delta": 0,
                                "detail": "╨Ю╤Б╤В╨░╨╜╨╛╨▓╨╗╨╡╨╜╨╛ ╨┐╨╛╨╗╤М╨╖╨╛╨▓╨░╤В╨╡╨╗╨╡╨╝",
                            }
                            _refresh_all_atomic_progress(failed=False)
                            _persist_refresh_all_run_item(
                                account.id,
                                status="cancelled",
                                worker=None,
                                detail="╨Ю╤Б╤В╨░╨╜╨╛╨▓╨╗╨╡╨╜╨╛ ╨┐╨╛╨╗╤М╨╖╨╛╨▓╨░╤В╨╡╨╗╨╡╨╝",
                            )
                            stop_requested.set()
                        except Exception as e:
                            from accounts.scrape_fallback_recovery import (
                                apify_fallback_detail_suffix,
                                notify_playwright_batch_errors,
                                try_apify_recovery_after_playwright_failure,
                            )

                            refresh_failure_exc = e
                            notify_playwright_batch_errors(
                                account,
                                e,
                                batch_ctx=batch_scrape,
                                fb_batch_guard=fb_batch_guard,
                            )
                            apify_recovered = False
                            try:
                                apify_acc = try_apify_recovery_after_playwright_failure(
                                    account,
                                    e,
                                    batch_ctx=batch_scrape,
                                    trigger=ApifyRefreshJobTrigger.REFRESH_ALL,
                                    parent_batch_id=apify_batch_id,
                                )
                            except Exception as apify_exc:
                                e = apify_exc
                                refresh_failure_exc = apify_exc
                            else:
                                if apify_acc is not None:
                                    refresh_failure_exc = None
                                    account = apify_acc
                                    account.refresh_from_db()
                                    row = {
                                        "id": account.id,
                                        "platform": account.platform,
                                        "username": account.username,
                                        "status": "╤Г╤Б╨┐╨╡╤И╨╜╨╛",
                                        "error": "",
                                        "follower_count": account.follower_count,
                                        "follower_delta": (
                                            int(account.follower_count or 0)
                                            - before["follower_count"]
                                        ),
                                        "like_count": account.like_count,
                                        "like_delta": (
                                            int(account.like_count or 0)
                                            - before["like_count"]
                                        ),
                                        "view_count": account.view_count,
                                        "view_delta": (
                                            int(account.view_count or 0)
                                            - before["view_count"]
                                        ),
                                        "post_count": account.post_count,
                                        "post_delta": (
                                            int(account.post_count or 0)
                                            - before["post_count"]
                                        ),
                                    }
                                    _refresh_all_atomic_progress(failed=False)
                                    _persist_refresh_all_run_item(
                                        account.id,
                                        status="done",
                                        worker=None,
                                        detail=apify_fallback_detail_suffix(
                                            batch_scrape, account
                                        ),
                                    )
                                    apify_recovered = True
                            if not apify_recovered:
                                detail, _ = _format_refresh_error(account, e)
                                row = {
                                    "id": account.id,
                                    "platform": account.platform,
                                    "username": account.username,
                                    "status": "╨╛╤И╨╕╨▒╨║╨░",
                                    "error": detail,
                                    "follower_count": before["follower_count"],
                                    "follower_delta": None,
                                    "like_count": before["like_count"],
                                    "like_delta": None,
                                    "view_count": before["view_count"],
                                    "view_delta": None,
                                    "post_count": before["post_count"],
                                    "post_delta": None,
                                }
                                _refresh_all_atomic_progress(
                                    failed=True, last_error=str(detail or "")
                                )
                                _persist_refresh_all_run_item(
                                    account.id,
                                    status="error",
                                    worker=None,
                                    detail=str(detail or "")[:800],
                                )
                        acc_mono_end = time.monotonic()
                        acc_wall_end = timezone.now()
                        if row is not None:
                            row["refresh_duration_sec"] = round(acc_mono_end - acc_mono_start, 3)
                            row["refresh_started_local"] = _refresh_all_local_dt_str(acc_wall_start)
                            row["refresh_finished_local"] = _refresh_all_local_dt_str(acc_wall_end)
                            if row.get("status") not in ("╨╛╤И╨╕╨▒╨║╨░", "╨╜╨╡ ╨▓╤Л╨┐╨╛╨╗╨╜╨╡╨╜╨╛"):
                                row["account_db_updated_local"] = _refresh_all_local_dt_str(account.updated_at)
                            else:
                                row["account_db_updated_local"] = ""
                    finally:
                        if attempted_network and not is_refresh_cancel_requested():
                            account_queue.set_platform_cooldown(
                                account.platform,
                                _refresh_all_cooldown_seconds(
                                    account,
                                    refresh_failure_exc,
                                ),
                            )
                            warm_tracker.after_network_refresh(account.platform)
                        if stop_requested.is_set() and row is None:
                            account_queue.abandon(idx, account.platform)
                        else:
                            account_queue.finish(idx, account.platform)

                    with report_lock:
                        report_by_index[idx] = row

            run_wall_start = timezone.now()
            run_mono_start = time.monotonic()
            with ThreadPoolExecutor(max_workers=worker_count) as executor:
                futures = submit_refresh_workers(
                    executor,
                    _worker,
                    worker_count=worker_count,
                    has_facebook=has_fb_accounts,
                )
                for f in futures:
                    f.result()

            warm_tracker.join_warm_threads(
                timeout=15.0 if is_refresh_cancel_requested() else None,
            )
            _finalize_refresh_all_run_detail_stale()

            report_rows: list[dict] = []
            for i, row in enumerate(report_by_index):
                if row is not None:
                    report_rows.append(row)
                    continue
                acc_nf = accounts[i]
                acc_nf.refresh_from_db()
                fb = int(acc_nf.follower_count or 0)
                lb = int(acc_nf.like_count or 0)
                vb = int(acc_nf.view_count or 0)
                pb = int(acc_nf.post_count or 0)
                report_rows.append({
                    "id": acc_nf.id,
                    "platform": acc_nf.platform,
                    "username": acc_nf.username,
                    "status": "╨╜╨╡ ╨▓╤Л╨┐╨╛╨╗╨╜╨╡╨╜╨╛",
                    "follower_count": fb,
                    "follower_delta": 0,
                    "like_count": lb,
                    "like_delta": 0,
                    "view_count": vb,
                    "view_delta": 0,
                    "post_count": pb,
                    "post_delta": 0,
                    "error": "╨╛╤Б╤В╨░╨╜╨╛╨▓╨║╨░ ╨┤╨╛ ╨╛╨▒╤А╨░╨▒╨╛╤В╨║╨╕ ╤Н╤В╨╛╨│╨╛ ╨░╨║╨║╨░╤Г╨╜╤В╨░",
                    "refresh_duration_sec": "",
                    "refresh_started_local": "",
                    "refresh_finished_local": "",
                    "account_db_updated_local": "",
                })

            _refresh_all_apply_completion_summary(report_rows)

            run_wall_end = timezone.now()
            run_mono_end = time.monotonic()
            run_duration_mono = max(0.0, run_mono_end - run_mono_start)
            st_counts = (
                RefreshAllState.objects.filter(pk=1)
                .values("processed_accounts", "success_accounts", "failed_accounts")
                .first()
                or {}
            )
            _refresh_all_save_report_csv(
                report_rows=report_rows,
                run_wall_start=run_wall_start,
                run_wall_end=run_wall_end,
                run_duration_mono_sec=run_duration_mono,
                worker_count=worker_count,
                processed_db=int(st_counts.get("processed_accounts") or 0),
                success_db=int(st_counts.get("success_accounts") or 0),
                failed_db=int(st_counts.get("failed_accounts") or 0),
            )

    except Exception as exc:
        logger.exception("refresh_all.background_failed")
        try:
            state = RefreshAllState.get()
            state.last_error = str(exc)
            state.save(update_fields=["last_error", "updated_at"])
        except Exception:
            pass
    finally:
        try:
            from platforms.rumble.scraper import release_batch_resources

            release_batch_resources()
        except Exception:
            pass
        try:
            from .facebook_refresh_lane import end_facebook_batch

            end_facebook_batch()
        except Exception:
            pass
        try:
            from platforms.apify.batch_guard import leave_sync_apify_batch

            leave_sync_apify_batch()
        except Exception:
            pass
        try:
            from platforms.worker_pool import shutdown_playwright_pool_aggressive

            shutdown_playwright_pool_aggressive()
        except Exception as e:
            print(f"[refresh_all] post-run browser cleanup failed: {e}", file=sys.stderr)
        if _prev_worker_autoclose is None:
            os.environ.pop("WORKER_AUTOCLOSE_BROWSER_ON_EXIT", None)
        else:
            os.environ["WORKER_AUTOCLOSE_BROWSER_ON_EXIT"] = _prev_worker_autoclose
        try:
            from integrations.links_sync import clear_refresh_all_links

            clear_refresh_all_links()
        except Exception:
            pass
        close_old_connections()
        try:
            fin = RefreshAllState.get()
            fin.refresh_from_db()
            fin.is_running = False
            fin.cancel_requested = False
            fin.current_account = ""
            fin.finished_at = timezone.now()
            fin.save(update_fields=[
                "is_running", "cancel_requested", "current_account",
                "finished_at", "updated_at",
            ])
        except Exception as e:
            logger.warning("refresh_all.finalize_state_failed", extra={"error": str(e)})


def _apply_refresh(account: Account, scraped: dict | None = None) -> Account:
    from .refresh_cancel import RefreshCancelledError

    def _load_baseline() -> dict:
        acc = Account.objects.get(pk=account.pk)
        return _account_refresh_baseline(acc)

    baseline = run_with_db_reconnect(_load_baseline)
    try:
        def _snapshot_before_scrape() -> tuple[Account, object]:
            acc2 = Account.objects.get(pk=account.pk)
            snap, _ = acc2.take_snapshot_if_needed()
            logger.info(
                "refresh.snapshot_before",
                extra={
                    "account_id": acc2.id,
                    "platform": acc2.platform,
                    "username": acc2.username,
                    "snapshot_date": str(snap.date),
                },
            )
            return acc2, snap

        acc, snap = run_with_db_reconnect(_snapshot_before_scrape)
        payload = scraped
        if payload is None:
            release_db_for_long_task()
            from .refresh_cancel import raise_if_refresh_cancel_requested

            raise_if_refresh_cancel_requested()
            from .facebook_refresh_lane import run_facebook_serialized

            payload = run_facebook_serialized(lambda: _scrape(acc), platform=acc.platform)
        ensure_fresh_db_connections()
        data = dict(payload)
        snap_pk = snap.pk
        return run_with_db_reconnect(
            lambda: _apply_refresh_after_scrape(account.pk, snap_pk, data),
        )
    except RefreshCancelledError:
        _restore_account_refresh_baseline(account.pk, baseline)
        raise
    except Exception:
        _restore_account_updated_at(account.pk, baseline.get("updated_at"))
        raise


def _apply_refresh_after_scrape(account_pk: int, snap_pk: int, data: dict) -> Account:
    from .refresh_cancel import raise_if_refresh_cancel_requested

    raise_if_refresh_cancel_requested()
    account = Account.objects.select_related("profile").get(pk=account_pk)
    snap = AccountSnapshot.objects.get(pk=snap_pk)
    logger.info(
        "refresh.scrape_result",
        extra={
            "account_id": account.id,
            "platform": account.platform,
            "username": account.username,
            "partial": bool(data.get("_partial", False)),
            "has_posts": "_posts" in data,
            "posts_count": len(data.get("_posts", []) or []),
            "posts_authoritative": bool(data.get("_posts_authoritative", True)),
        },
    )
    stats_before = {f: int(getattr(account, f) or 0) for f in _STAT_FIELDS}
    account.profile_unavailable = False
    # _partial=True means we only have non-stat fields (e.g. avatar from authenticated HTML
    # when follower counts were unavailable) тАФ preserve existing DB stats.
    is_partial = data.pop("_partial", False)
    posts_authoritative = data.pop("_posts_authoritative", True)
    has_posts_key = "_posts" in data
    posts = data.pop("_posts", [])
    scrape_included_avatar = "avatar_url" in data
    scraped_avatar_url = data.get("avatar_url") if scrape_included_avatar else None
    for field, value in data.items():
        if not hasattr(account, field):
            # Some scrapers return extra fields (e.g. following_count) that are
            # not stored in Account model; skip them without breaking refresh.
            continue
        # Username тАФ ╨║╨╗╤О╤З ╤Г╨╜╨╕╨║╨░╨╗╤М╨╜╨╛╤Б╤В╨╕; ╤Б╨║╤А╨░╨┐╨╡╤А ╨╜╨╡ ╨┤╨╛╨╗╨╢╨╡╨╜ ╨┐╨╛╨┤╨╝╨╡╨╜╤П╤В╤М @╨║╨╕╤А╨╕╨╗╨╗╨╕╤Ж╨░ ╨╜╨░ UCтАж.
        if field == "username":
            continue
        # _partial ╤Г Instagram ╤Б╤В╨░╨▓╨╕╤В╤Б╤П, ╨║╨╛╨│╨┤╨░ ╤Б╨╛╨▒╤А╨░╨╗╨╕ ╨╝╨╡╨╜╤М╤И╨╡ ╨┐╨╛╤Б╤В╨╛╨▓, ╤З╨╡╨╝ ╨╖╨░╤П╨▓╨╗╨╡╨╜╨╛ ╨▓
        # ╨┐╤А╨╛╤Д╨╕╨╗╨╡ (191 ╨┐╨╛╤Б╤В, ╤Б╨╛╨▒╤А╨░╨╜╨╛ 36). ╨н╤В╨╛ ╤Г╤В╨▓╨╡╤А╨╢╨┤╨╡╨╜╨╕╨╡ ╨┐╤А╨╛ ╤Б╨┐╨╕╤Б╨╛╨║ ╨┐╨╛╤Б╤В╨╛╨▓, ╨░ ╨╜╨╡
        # ╨┐╤А╨╛ ╨▓╤Б╤О ╤Б╤В╨░╤В╨╕╤Б╤В╨╕╨║╤Г: ╨┐╨╛╨┤╨┐╨╕╤Б╤З╨╕╨║╨╕ ╨▒╨╡╤А╤Г╤В╤Б╤П ╤Б╨╛ ╤Б╤В╤А╨░╨╜╨╕╤Ж╤Л ╨┐╤А╨╛╤Д╨╕╨╗╤П ╨╕ ╨║ ╨┐╨╛╤Б╤В╨░╨╝
        # ╨╛╤В╨╜╨╛╤И╨╡╨╜╨╕╤П ╨╜╨╡ ╨╕╨╝╨╡╤О╤В. ╨а╨░╨╜╤М╤И╨╡ ╤Д╨╗╨░╨│ ╨▓╤Л╨▒╤А╨░╤Б╤Л╨▓╨░╨╗ ╨╕ ╨╕╤Е ╤В╨╛╨╢╨╡ тАФ ╨┐╨╛╤Н╤В╨╛╨╝╤Г ╨▓ ╨▒╨░╨╖╨╡
        # ╤Б╤В╨╛╤П╨╗╨╕ ╨╜╤Г╨╗╨╕ ╨┐╤А╨╕ ╨╕╤Б╨┐╤А╨░╨▓╨╜╨╛ ╤Б╨╜╤П╤В╤Л╤Е 456 000. ╨Ю╤В ╨╖╨░╨╜╤Г╨╗╨╡╨╜╨╕╤П ╨┐╨╛╨┤╨┐╨╕╤Б╤З╨╕╨║╨╛╨▓
        # ╨╖╨░╤Й╨╕╤Й╨░╨╡╤В ╨┐╤А╨╛╨▓╨╡╤А╨║╨░ ╨╜╨╕╨╢╨╡: ╨╜╨╛╨╗╤М ╨╜╨╡ ╨╖╨░╤В╨╕╤А╨░╨╡╤В ╨╢╨╕╨▓╨╛╨╡ ╤З╨╕╤Б╨╗╨╛.
        if is_partial and field in _POST_DERIVED_STAT_FIELDS:
            continue  # ╨╜╨╡╨┐╨╛╨╗╨╜╤Л╨╣ ╤Б╨┐╨╕╤Б╨╛╨║ ╨┐╨╛╤Б╤В╨╛╨▓ тАФ ╤Б╤З╨╕╤В╨░╨╡╨╝ ╨░╨│╤А╨╡╨│╨░╤В╤Л ╨┐╨╛ ╨▒╨░╨╖╨╡, ╨░ ╨╜╨╡ ╨┐╨╛ ╨╜╨╡╨╝╤Г
        # ╨Э╨╛╨╗╤М ╨┐╨╛╨▓╨╡╤А╤Е ╨╢╨╕╨▓╨╛╨│╨╛ ╤З╨╕╤Б╨╗╨░ тАФ ╨┐╨╛╤З╤В╨╕ ╨▓╤Б╨╡╨│╨┤╨░ ╨╜╨╡╤Г╨┤╨░╨▓╤И╨╕╨╣╤Б╤П ╤Б╤К╤С╨╝, ╨░ ╨╜╨╡ ╤А╨╡╨░╨╗╤М╨╜╨╛╨╡
        # ╨┐╨░╨┤╨╡╨╜╨╕╨╡ ╨┤╨╛ ╨╜╤Г╨╗╤П. ╨д╨╗╨░╨│ _partial ╤Б╨┐╨░╤Б╨░╨╡╤В ╤В╨╛╨╗╤М╨║╨╛ ╨║╨╛╨│╨┤╨░ ╨╜╨╡ ╤Б╨╛╨▒╤А╨░╨╗╨╛╤Б╤М ╨▓╨╛╨╛╨▒╤Й╤С
        # ╨╜╨╕╤З╨╡╨│╨╛; ╤З╨░╤Б╤В╨╕╤З╨╜╤Л╨╣ ╨╛╤В╨▓╨╡╤В (Instagram ╨╛╤В╨┤╨░╨╗ ╨┐╤А╨╛╤Б╨╝╨╛╤В╤А╤Л ╨╕ ╨┐╨╛╤Б╤В╤Л, ╨░ ╨┐╨╛╨┤╨┐╨╕╤Б╤З╨╕╨║╨╛╨▓
        # ╨╕ ╨╗╨░╨╣╨║╨╕ тАФ ╨╜╤Г╨╗╤П╨╝╨╕) ╨┐╤А╨╛╤Е╨╛╨┤╨╕╨╗ ╨╝╨╕╨╝╨╛ ╨╜╨╡╨│╨╛ ╨╕ ╨╖╨░╤В╨╕╤А╨░╨╗ ╨╜╨░╨║╨╛╨┐╨╗╨╡╨╜╨╜╨╛╨╡.
        if (
            field in _STAT_FIELDS
            and not value
            and stats_before.get(field, 0) > 0
        ):
            logger.info(
                "refresh.keep_stat_on_zero",
                extra={
                    "account_id": account.id,
                    "platform": account.platform,
                    "username": account.username,
                    "field": field,
                    "kept": stats_before.get(field, 0),
                },
            )
            continue
        if value is not None:
            if field in _SKIP_EMPTY_STR_UPDATE and isinstance(value, str) and not value.strip():
                continue
            if account.platform == Platform.FACEBOOK and isinstance(value, str):
                if field == "display_name":
                    from platforms.facebook.profile_meta import is_junk_facebook_display_name

                    if is_junk_facebook_display_name(value):
                        continue
                if field == "avatar_url":
                    from platforms.facebook.profile_meta import is_usable_facebook_avatar_url

                    if not is_usable_facebook_avatar_url(value):
                        continue
            setattr(account, field, value)

    if account.platform == Platform.TIKTOK:
        # Apify/╨┐╨░╤А╤Б╨╡╤А ╨╝╨╛╨│╤Г╤В ╨╖╨░╨╜╨╕╨╖╨╕╤В╤М heart ╨╛╤В╨╜╨╛╤Б╨╕╤В╨╡╨╗╤М╨╜╨╛ UI; ╨╜╨╡ ╤А╨╛╨╜╤П╨╡╨╝ ╨╗╨░╨╣╨║╨╕ ╨┐╤А╨╛╤Д╨╕╨╗╤П ╨┐╤А╨╕ refresh.
        account.like_count = max(
            int(stats_before.get("like_count", 0) or 0),
            int(account.like_count or 0),
        )
        # videoCount ╨╕╨╖ ╤И╨░╨┐╨║╨╕ ╨▒╨╡╨╖ ╤Б╨┐╨╕╤Б╨║╨░ ╨┐╨╛╤Б╤В╨╛╨▓ тАФ ╤В╨╛╨╗╤М╨║╨╛ ╤Д╨░╨║╤В╨╕╤З╨╡╤Б╨║╨╕╨╡ ╨┐╨╛╤Б╤В╤Л ╨▓ ╨С╨Ф.
        if has_posts_key and not posts_authoritative and not posts:
            account.post_count = _posts_for_account_stats(account).count()

    seen_post_external_ids: set[str] = set()
    with transaction.atomic():
        if has_posts_key and (posts_authoritative or posts):
            try:
                seen_post_external_ids = _sync_posts(
                    account,
                    posts,
                    mark_unseen_missing=False,
                )
                logger.info(
                    "refresh.posts_synced",
                    extra={
                        "account_id": account.id,
                        "platform": account.platform,
                        "username": account.username,
                        "posts_count": len(posts),
                        "posts_authoritative": posts_authoritative,
                    },
                )
            except Exception:
                logger.exception(
                    "refresh.posts_sync_failed",
                    extra={"account_id": account.id, "platform": account.platform, "username": account.username},
                )
        elif has_posts_key and not posts_authoritative:
            print(
                f"[posts] keeping existing posts for @{account.username}: "
                "empty non-authoritative list from scraper",
            )

        _apply_post_aggregates_to_account(account, stats_before)

        if not _refresh_stats_trustworthy(account, stats_before):
            raise ValueError(
                "╨Ф╨░╨╜╨╜╤Л╨╡ ╨▓╤Л╨│╨╗╤П╨┤╤П╤В ╨║╨░╨║ ╨╛╤И╨╕╨▒╨║╨░ ╨╕╨╗╨╕ ╨╜╨╡╨┤╨╛╤Б╤В╤Г╨┐╨╜╨╛╤Б╤В╤М: ╨╜╤Г╨╗╨╡╨▓╤Л╨╡ ╨╝╨╡╤В╤А╨╕╨║╨╕ ╨┐╤А╨╕ ╨╜╨╡╨╜╤Г╨╗╨╡╨▓╤Л╤Е ╨▓ ╨▒╨░╨╖╨╡ "
                "╨╕╨╗╨╕ ╨┐╤А╨╛╤Д╨╕╨╗╤М ╨┐╨╛╨╝╨╡╤З╨╡╨╜ ╨╜╨╡╨┤╨╛╤Б╤В╤Г╨┐╨╜╤Л╨╝. ╨Ю╨▒╨╜╨╛╨▓╨╗╨╡╨╜╨╕╨╡ ╨╜╨╡ ╨┐╤А╨╕╨╝╨╡╨╜╨╡╨╜╨╛."
            )

        raise_if_refresh_cancel_requested()

        if has_posts_key and posts_authoritative:
            _mark_unseen_posts_missing(account, seen_post_external_ids)

        try:
            from integrations.links_sync import sync_link_clicks_for_account

            account.link_click_count = sync_link_clicks_for_account(account)
        except Exception as exc:
            logger.warning(
                "refresh.links_sync_failed",
                extra={"account_id": account.id, "error": str(exc)},
            )

        account.updated_at = timezone.now()
        account.save(update_fields=list(_ACCOUNT_REFRESH_SAVE_FIELDS))

        from .avatar_storage import ensure_account_avatar_after_refresh

        account.refresh_from_db(fields=["avatar_url", "avatar_file", "avatar_missing"])
        ensure_account_avatar_after_refresh(
            account,
            scrape_included_avatar=scrape_included_avatar,
            scraped_avatar_url=scraped_avatar_url,
        )

        # Keep today's snapshot up-to-date with the freshly-scraped/aggregated values.
        # This is the baseline used by tomorrow's delta calculation.
        snap.follower_count = account.follower_count
        snap.like_count = account.like_count
        snap.view_count = account.view_count
        snap.post_count = account.post_count
        snap.link_click_count = account.link_click_count
        snap.save(update_fields=[
            "follower_count", "like_count", "view_count", "post_count", "link_click_count",
        ])
        logger.info(
            "refresh.snapshot_after",
            extra={
                "account_id": account.id,
                "platform": account.platform,
                "username": account.username,
                "snapshot_date": str(snap.date),
                "follower_count": account.follower_count,
                "like_count": account.like_count,
                "view_count": account.view_count,
                "post_count": account.post_count,
            },
        )

        # Fix zero-value snapshots from before the first real scrape.
        # Without this, any previous day's snapshot with all zeros causes tomorrow's
        # delta to show the full subscriber count as a single-day gain.
        account.snapshots.filter(
            date__lt=snap.date,
            follower_count=0,
            post_count=0,
        ).update(
            follower_count=account.follower_count,
            like_count=account.like_count,
            view_count=account.view_count,
            post_count=account.post_count,
            link_click_count=account.link_click_count,
        )

        # Fix snapshots where view_count is still 0 тАФ these are snapshots created
        # before the view_count field was added to AccountSnapshot (migration 0006).
        # Without this, delta = current_view_count - 0 = full count (wrong).
        account.snapshots.filter(
            date__lt=snap.date,
            view_count=0,
        ).update(view_count=account.view_count)

        # Fix snapshots where post_count is still 0 тАФ happens when a scraper only
        # recently started returning post_count (e.g. Threads). Without this, the
        # first refresh would show the entire post count as a single-day delta.
        if account.post_count:
            account.snapshots.filter(
                date__lt=snap.date,
                post_count=0,
            ).update(post_count=account.post_count)

        # For YouTube / Telegram / Instagram / X / Threads: like_count in old snapshots
        # was 0 because it's post-derived, not a platform-level counter.
        # Bring old zero snapshots in line with the current aggregated value.
        if account.platform in (
            Platform.YOUTUBE, Platform.TELEGRAM, Platform.INSTAGRAM,
            Platform.X, Platform.THREADS, Platform.RUMBLE, Platform.REDDIT,
            Platform.FACEBOOK,
        ):
            account.snapshots.filter(
                date__lt=snap.date,
                like_count=0,
            ).update(like_count=account.like_count)

    try:
        from .auto_refresh_pulse import record_account_refresh_platform_delta

        record_account_refresh_platform_delta(
            account.platform,
            stats_before["view_count"],
            int(account.view_count or 0),
            source="refresh",
        )
    except Exception as exc:
        logger.warning(
            "refresh.auto_refresh_pulse_failed",
            extra={"account_id": account.id, "error": str(exc)},
        )

    return account


def _refresh_with_retry(account: Account, scraped: dict | None = None) -> Account:
    """
    ╨б╨║╤А╨░╨┐╨╕╨╜╨│ ╨╛╨┤╨╕╨╜ ╤А╨░╨╖; ╨╖╨░╨┐╨╕╤Б╤М ╨▓ ╨С╨Ф тАФ ╤Б ╨┐╨╡╤А╨╡╨┐╨╛╨┤╨║╨╗╤О╤З╨╡╨╜╨╕╨╡╨╝ (╨┐╨╛╤Б╨╗╨╡ ╨┤╨╛╨╗╨│╨╛╨│╨╛ worker).
    """
    from .refresh_cancel import RefreshCancelledError, raise_if_refresh_cancel_requested

    pk = account.pk
    payload = dict(scraped) if scraped is not None else None

    def _snapshot() -> object:
        acc = Account.objects.get(pk=pk)
        snap, _ = acc.take_snapshot_if_needed()
        logger.info(
            "refresh.snapshot_before",
            extra={
                "account_id": acc.id,
                "platform": acc.platform,
                "username": acc.username,
                "snapshot_date": str(snap.date),
            },
        )
        return snap

    snap = run_with_db_reconnect(_snapshot)
    snap_pk = snap.pk
    if payload is None:
        release_db_for_long_task()
        raise_if_refresh_cancel_requested()
        acc = Account.objects.get(pk=pk)
        payload = _scrape(acc)

    db_attempts = int(getattr(settings, "REFRESH_DB_RETRY_ATTEMPTS", 6) or 6)
    db_attempts = max(3, min(db_attempts, 10))
    payload_copy = dict(payload)
    last_exc: Exception | None = None
    for attempt in range(db_attempts):
        ensure_fresh_db_connections()
        try:
            return run_with_db_reconnect(
                lambda: _apply_refresh_after_scrape(pk, snap_pk, dict(payload_copy)),
            )
        except ValueError:
            raise
        except RefreshCancelledError:
            raise
        except Exception as exc:
            last_exc = exc
            msg = str(exc).lower()
            if "╨╜╨╡ ╨╜╨░╨╣╨┤╨╡╨╜" in msg or "not found" in msg:
                raise
            if not _stale_db_connection_error(exc) or attempt >= db_attempts - 1:
                raise
            time.sleep(0.4 + attempt * 0.5)
    assert last_exc is not None
    raise last_exc


class AccountViewSet(viewsets.ModelViewSet):
    serializer_class = AccountSerializer

    def get_queryset(self):
        # ╨Ф╨╗╤П detail-╨╛╨┐╨╡╤А╨░╤Ж╨╕╨╣ ╨░╨║╨║╨░╤Г╨╜╤В ╨┤╨╛╨╗╨╢╨╡╨╜ ╨▒╤Л╤В╤М ╨┤╨╛╤Б╤В╤Г╨┐╨╡╨╜ ╨┐╨╛ ID ╨┤╨░╨╢╨╡ ╨╡╤Б╨╗╨╕ ╨╛╨╜
        # ╤Б╨║╤А╤Л╤В ╨│╨╗╨╛╨▒╨░╨╗╤М╨╜╤Л╨╝╨╕ ╤Д╨╕╨╗╤М╤В╤А╨░╨╝╨╕ (╨╕╨╜╨░╤З╨╡ delete/retrieve ╨┤╨░╤О╤В 404).
        action = getattr(self, "action", "")
        force_include_hidden_for_detail = action in {
            "retrieve",
            "update",
            "partial_update",
            "destroy",
            "refresh",
            "posts",
        }
        include_hidden = force_include_hidden_for_detail or _coerce_bool(
            self.request.query_params.get("include_hidden"),
        )
        include_hidden_platforms = include_hidden or _coerce_bool(
            self.request.query_params.get("include_hidden_platforms"),
        )
        include_hidden_profiles = include_hidden or _coerce_bool(
            self.request.query_params.get("include_hidden_profiles"),
        )
        today = timezone.localdate()
        period_days = _effective_account_delta_period_days(self.request)
        cutoff = today - datetime.timedelta(days=period_days)
        prev_snapshots = AccountSnapshot.objects.filter(
            account=OuterRef("pk"),
            date__lte=cutoff,
        ).order_by("-date")

        qs = Account.objects.select_related("profile", "owner", "group", "country").annotate(
            _prev_follower_count=Coalesce(
                Subquery(prev_snapshots.values("follower_count")[:1]),
                Value(0),
                output_field=BigIntegerField(),
            ),
            _prev_like_count=Coalesce(
                Subquery(prev_snapshots.values("like_count")[:1]),
                Value(0),
                output_field=BigIntegerField(),
            ),
            _prev_view_count=Coalesce(
                Subquery(prev_snapshots.values("view_count")[:1]),
                Value(0),
                output_field=BigIntegerField(),
            ),
            _prev_post_count=Coalesce(
                Subquery(prev_snapshots.values("post_count")[:1]),
                Value(0),
                output_field=IntegerField(),
            ),
            _prev_link_click_count=Coalesce(
                Subquery(prev_snapshots.values("link_click_count")[:1]),
                Value(0),
                output_field=BigIntegerField(),
            ),
        ).annotate(
            _raw_view_delta=F("view_count") - F("_prev_view_count"),
            _follower_delta=F("follower_count") - F("_prev_follower_count"),
            _like_delta=F("like_count") - F("_prev_like_count"),
            _post_delta=F("post_count") - F("_prev_post_count"),
            _link_click_delta=F("link_click_count") - F("_prev_link_click_count"),
        ).annotate(
            _view_delta=Case(
                When(
                    (Q(platform=Platform.INSTAGRAM) | Q(platform=Platform.THREADS))
                    & Q(_raw_view_delta__lt=0),
                    then=Value(0),
                ),
                default=F("_raw_view_delta"),
                output_field=IntegerField(),
            ),
        )
        platform = self.request.query_params.get("platform")
        if platform:
            qs = qs.filter(platform=platform)
        profile_id = self.request.query_params.get("profile_id")
        if profile_id == "none":
            qs = qs.filter(profile__isnull=True)
        elif profile_id:
            qs = qs.filter(profile_id=profile_id)
        group_id = self.request.query_params.get("group_id")
        if group_id == "none":
            qs = qs.filter(group__isnull=True)
        elif group_id:
            qs = qs.filter(group_id=group_id)
        country_id = self.request.query_params.get("country_id")
        if country_id == "none":
            qs = qs.filter(country__isnull=True)
        elif country_id:
            qs = qs.filter(country_id=country_id)
        search = self.request.query_params.get("search", "").strip()
        if search:
            qs = qs.filter(
                Q(username__icontains=search) | Q(display_name__icontains=search)
            )
        if not force_include_hidden_for_detail:
            qs = _apply_archived_filter(qs, self.request.query_params.get("archived"))
            qs = _apply_banned_filter(qs, self.request.query_params.get("banned"))
            # ╨Ф╨╛╨╝╨╡╨╜ тАФ ╤Б╨░╨╝╤Л╨╣ ╨▓╨╡╤А╤Е╨╜╨╕╨╣ ╤Д╨╕╨╗╤М╤В╤А. ╨Э╨░ detail ╨╜╨╡ ╨╜╨░╨║╨╗╨░╨┤╤Л╨▓╨░╨╡╨╝: ╨░╨║╨║╨░╤Г╨╜╤В
            # ╨┤╨╛╨╗╨╢╨╡╨╜ ╨╛╤В╨║╤А╤Л╨▓╨░╤В╤М╤Б╤П ╨╕ ╨┐╤А╨░╨▓╨╕╤В╤М╤Б╤П ╨┐╨╛ ID, ╨╕╨╜╨░╤З╨╡ delete/retrieve ╨┤╨░╤О╤В
            # 404 ╤А╨╛╨▓╨╜╨╛ ╨║╨░╨║ ╨╕ ╤Б ╨╛╤Б╤В╨░╨╗╤М╨╜╤Л╨╝╨╕ ╤Б╨║╤А╤Л╨▓╨░╤О╤Й╨╕╨╝╨╕ ╤Д╨╕╨╗╤М╤В╤А╨░╨╝╨╕ ╨▓╤Л╤И╨╡.
            qs = domains.narrow(qs, domains.resolve(self.request))
        return _apply_visibility_filters(
            qs,
            include_hidden_platforms=include_hidden_platforms,
            include_hidden_profiles=include_hidden_profiles,
        )

    def perform_create(self, serializer):
        super().perform_create(serializer)
        _stamp_new_account_updated_at(serializer.instance.pk)
        serializer.instance.refresh_from_db(fields=["updated_at"])

    def perform_update(self, serializer):
        """╨б╨╝╨╡╨╜╨░ ╨┐╤А╨╛╤Д╨╕╨╗╤П/╨▓╨╗╨░╨┤╨╡╨╗╤М╤Ж╨░/╨│╤А╤Г╨┐╨┐╤Л/╤Б╤В╤А╨░╨╜╤Л ╨╜╨╡ ╨┤╨▓╨╕╨│╨░╨╡╤В ┬л╨Ю╨▒╨╜╨╛╨▓╨╗╤С╨╜┬╗ тАФ ╤В╨╛╨╗╤М╨║╨╛ ╤Г╤Б╨┐╨╡╤И╨╜╤Л╨╣ refresh ╤Б╤В╨░╤В╨╕╤Б╤В╨╕╨║╨╕."""
        validated = serializer.validated_data
        if _account_assignment_only_validated(validated):
            serializer.save(update_fields=_account_assignment_update_fields(validated))
            return
        serializer.save()

    def get_serializer_context(self):
        ctx = super().get_serializer_context()
        ctx["hidden_platforms"] = _get_hidden_platforms()
        ctx["account_delta_period_days"] = _effective_account_delta_period_days(self.request)
        return ctx

    def create(self, request, *args, **kwargs):
        """
        ╨Ш╨╝╨┐╨╛╤А╤В ╤Б╨┐╨╕╤Б╨║╨░: ╤Б╤Г╤Й╨╡╤Б╤В╨▓╤Г╤О╤Й╨╕╨╣ ╨░╨║╨║╨░╤Г╨╜╤В тАФ ╤В╨╛╨╗╤М╨║╨╛ ╤Б╨╝╨╡╨╜╨░ ╨┐╤А╨╛╤Д╨╕╨╗╤П/╨▓╨╗╨░╨┤╨╡╨╗╤М╤Ж╨░/╨│╤А╤Г╨┐╨┐╤Л/╤Б╤В╤А╨░╨╜╤Л
        (╤Б╤В╨░╤В╨╕╤Б╤В╨╕╨║╨░ ╨╕ ┬л╨Ю╨▒╨╜╨╛╨▓╨╗╤С╨╜┬╗ ╨╜╨╡ ╤В╤А╨╛╨│╨░╨╡╨╝). ╨С╨╡╨╖ ╨╕╨╖╨╝╨╡╨╜╨╡╨╜╨╕╨╣ тАФ ╨╡╤Б╨╗╨╕ ╨▓╤Б╨╡ ╨┐╨╡╤А╨╡╨┤╨░╨╜╨╜╤Л╨╡ ╨┐╨╛╨╗╤П ╤В╨╡ ╨╢╨╡.
        """
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        validated = serializer.validated_data
        username = validated["username"]
        platform = validated["platform"]

        existing = Account.objects.filter(username=username, platform=platform).first()
        if existing is not None:
            ctx = self.get_serializer_context()
            unarchived = _unarchive_account_on_import(existing)
            unbanned = _unban_account_on_import(existing)
            if _existing_account_assignment_unchanged(existing, validated):
                if not unarchived and not unbanned:
                    data = self.get_serializer(existing, context=ctx).data
                    data["import_action"] = "unchanged"
                    return Response(data, status=status.HTTP_200_OK)
                existing.refresh_from_db()
                data = self.get_serializer(existing, context=ctx).data
                if unarchived and unbanned:
                    data["import_action"] = "restored"
                elif unarchived:
                    data["import_action"] = "unarchived"
                else:
                    data["import_action"] = "unbanned"
                return Response(data, status=status.HTTP_200_OK)
            changed_fields = _apply_existing_account_assignment(existing, validated)
            if unarchived:
                changed_fields = [*changed_fields, "is_archived"]
            if unbanned:
                changed_fields = [*changed_fields, "is_banned"]
            existing.refresh_from_db()
            data = self.get_serializer(existing, context=ctx).data
            data["import_action"] = "assignment_updated"
            data["changed_fields"] = changed_fields
            return Response(data, status=status.HTTP_200_OK)

        self.perform_create(serializer)
        headers = self.get_success_headers(serializer.data)
        data = dict(serializer.data)
        data["import_action"] = "created"
        return Response(data, status=status.HTTP_201_CREATED, headers=headers)

    @action(detail=True, methods=["post"])
    def refresh(self, request, pk=None):
        account = self.get_object()
        from accounts.scrape_backend import should_use_apify_for_account

        if should_use_apify_for_account(account):
            from accounts.models import ApifyRefreshJobTrigger
            from platforms.apify.dispatch import dispatch_apify_refresh

            with _account_refresh_mutex(account.id):
                job = dispatch_apify_refresh(account, trigger=ApifyRefreshJobTrigger.MANUAL)
            return Response(
                {
                    "job_id": job.pk,
                    "apify_run_id": job.apify_run_id or None,
                    "status": job.status,
                    "detail": "╨Ч╨░╨┐╤Г╤Й╨╡╨╜ ╤Б╨▒╨╛╤А Apify",
                },
                status=status.HTTP_202_ACCEPTED,
            )
        with _account_refresh_mutex(account.id):
            # ╨Я╨╛╤Б╨╗╨╡ ┬л╨Ю╤Б╤В╨░╨╜╨╛╨▓╨╕╤В╤М ╨░╨▓╤В╨╛╨╛╨▒╨╜╨╛╨▓╨╗╨╡╨╜╨╕╨╡┬╗ force_stop ╨▒╨╗╨╛╨║╨╕╤А╤Г╨╡╤В Playwright ╨┤╨╛ ╤Б╨▒╤А╨╛╤Б╨░.
            try:
                from .refresh_state import clear_orphan_cancel_flags

                clear_orphan_cancel_flags()
            except Exception:
                pass
            refreshed, detail, code = _refresh_account_for_api(account)
            if refreshed is not None:
                return Response(AccountSerializer(refreshed, context=self.get_serializer_context()).data)
            return Response({"detail": detail}, status=code)

    @action(detail=False, methods=["post"], url_path="bulk-refresh")
    def bulk_refresh(self, request):
        """
        ╨Ч╨░╨┐╤Г╤Б╤В╨╕╤В╤М ╤Д╨╛╨╜╨╛╨▓╨╛╨╡ ╨╛╨▒╨╜╨╛╨▓╨╗╨╡╨╜╨╕╨╡ ╨▓╤Л╨▒╤А╨░╨╜╨╜╤Л╤Е ╨░╨║╨║╨░╤Г╨╜╤В╨╛╨▓ (╤Б╤В╨░╤В╤Г╤Б тАФ auto-refresh-status).
        ╨Ф╨╗╤П ╨╜╨╡╤Б╨║╨╛╨╗╤М╨║╨╕╤Е Instagram: ╨╛╨┤╨╕╨╜ Playwright-╤Б╨╡╨░╨╜╤Б ╨╜╨░ ╨▓╤Б╨╡ /reels/ ╨▓ ╤Д╨╛╨╜╨╛╨▓╨╛╨╝ ╨┐╨╛╤В╨╛╨║╨╡.
        """
        ids = request.data.get("ids")
        if not isinstance(ids, list) or not ids:
            return Response(
                {"detail": "╨Я╨╡╤А╨╡╨┤╨░╨╣╤В╨╡ ╨╝╨░╤Б╤Б╨╕╨▓ ids"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        id_ints: list[int] = []
        for raw in ids:
            try:
                id_ints.append(int(raw))
            except (TypeError, ValueError):
                continue
        if not id_ints:
            return Response(
                {"detail": "╨Т ids ╨┤╨╛╨╗╨╢╨╜╤Л ╨▒╤Л╤В╤М ╤З╨╕╤Б╨╗╨╛╨▓╤Л╨╡ ╨╕╨┤╨╡╨╜╤В╨╕╤Д╨╕╨║╨░╤В╨╛╤А╤Л ╨░╨║╨║╨░╤Г╨╜╤В╨╛╨▓"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        by_id = {a.id: a for a in Account.objects.filter(id__in=id_ints).select_related("profile")}
        ordered: list[Account] = []
        for i in id_ints:
            if i in by_id:
                ordered.append(by_id[i])
        if not ordered:
            return Response({"detail": "╨Р╨║╨║╨░╤Г╨╜╤В╤Л ╨╜╨╡ ╨╜╨░╨╣╨┤╨╡╨╜╤Л"}, status=status.HTTP_404_NOT_FOUND)

        with _refresh_all_start_lock:
            state = AutoRefreshState.get()
            rr = RefreshAllState.get()
            if state.is_running or rr.is_running:
                return Response(
                    {"detail": "╨б╨╡╨╣╤З╨░╤Б ╤Г╨╢╨╡ ╨▓╤Л╨┐╨╛╨╗╨╜╤П╨╡╤В╤Б╤П ╨┤╤А╤Г╨│╨╛╨╡ ╨░╨▓╤В╨╛╨╛╨▒╨╜╨╛╨▓╨╗╨╡╨╜╨╕╨╡/╨╛╨▒╨╜╨╛╨▓╨╗╨╡╨╜╨╕╨╡."},
                    status=status.HTTP_409_CONFLICT,
                )
            skip_recent_hours, skip_cutoff = _schedule_skip_recent_cutoff()
            from .refresh_skip_recent import build_initial_run_detail_items

            run_items, skip_initial = build_initial_run_detail_items(
                ordered,
                skip_recent_hours=skip_recent_hours,
                cutoff=skip_cutoff,
            )
            state.is_running = True
            state.source = "bulk_refresh"
            state.cancel_requested = False
            state.total_accounts = len(ordered)
            state.processed_accounts = skip_initial
            state.success_accounts = skip_initial
            state.failed_accounts = 0
            state.current_account = ""
            state.last_error = ""
            state.started_at = timezone.now()
            state.finished_at = None
            worker_count = _parallel_refresh_worker_count(ordered)
            state.run_detail = {"items": run_items, "worker_count": worker_count}
            state.save(update_fields=[
                "is_running", "source", "cancel_requested", "total_accounts",
                "processed_accounts", "success_accounts", "failed_accounts",
                "current_account", "last_error", "started_at", "finished_at",
                "run_detail", "updated_at",
            ])
        threading.Thread(
            target=_run_bulk_refresh_background,
            kwargs={"account_ids": id_ints},
            daemon=True,
            name="bulk-refresh",
        ).start()
        return Response({"started": True, "total_accounts": len(ordered)})

    @action(detail=False, methods=["post"], url_path="bulk-update")
    def bulk_update(self, request):
        """╨Ь╨░╤Б╤Б╨╛╨▓╨╛ ╨╛╨▒╨╜╨╛╨▓╨╕╤В╤М ╨┐╨╛╨╗╤П ╨▓╤Л╨▒╤А╨░╨╜╨╜╤Л╤Е ╨░╨║╨║╨░╤Г╨╜╤В╨╛╨▓ (╨┤╨╛╨╝╨╡╨╜/╨┐╤А╨╛╤Д╨╕╨╗╤М/╨▓╨╗╨░╨┤╨╡╨╗╨╡╤Ж/╨│╤А╤Г╨┐╨┐╨░/╤Б╤В╤А╨░╨╜╨░/╨░╤А╤Е╨╕╨▓)."""
        id_ints = _parse_account_ids_list(request.data.get("ids"))
        if id_ints is None:
            return Response(
                {"detail": "╨Я╨╡╤А╨╡╨┤╨░╨╣╤В╨╡ ╨╝╨░╤Б╤Б╨╕╨▓ ids"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if not id_ints:
            return Response(
                {"detail": "╨Т ids ╨┤╨╛╨╗╨╢╨╜╤Л ╨▒╤Л╤В╤М ╤З╨╕╤Б╨╗╨╛╨▓╤Л╨╡ ╨╕╨┤╨╡╨╜╤В╨╕╤Д╨╕╨║╨░╤В╨╛╤А╤Л ╨░╨║╨║╨░╤Г╨╜╤В╨╛╨▓"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        data = request.data if isinstance(request.data, dict) else {}
        updates: dict = {}
        update_fields: list[str] = []

        fk_map = (
            # ╨Ф╨╛╨╝╨╡╨╜ ╨╖╨┤╨╡╤Б╤М ╨╢╨╡: ╤Н╤В╨╛ ╤В╨░╨║╨╛╨╡ ╨╢╨╡ ╨╜╨░╨╖╨╜╨░╤З╨╡╨╜╨╕╨╡, ╨║╨░╨║ ╨┐╤А╨╛╤Д╨╕╨╗╤М ╨╕╨╗╨╕ ╨▓╨╗╨░╨┤╨╡╨╗╨╡╤Ж,
            # ╨╕ ╤А╨░╤Б╨║╨╗╨░╨┤╤Л╨▓╨░╤В╤М ╨░╨║╨║╨░╤Г╨╜╤В╤Л ╨┐╨╛ ╨┤╨╛╨╝╨╡╨╜╨░╨╝ ╨╜╨░╨┤╨╛ ╤В╨╡╨╝╨╕ ╨╢╨╡ ╨╝╨░╤Б╤Б╨╛╨▓╤Л╨╝╨╕ ╨┤╨╡╨╣╤Б╤В╨▓╨╕╤П╨╝╨╕.
            ("domain_id", "domain_id", Domain),
            ("profile_id", "profile_id", Profile),
            ("owner_id", "owner_id", Owner),
            ("group_id", "group_id", AccountGroup),
            ("country_id", "country_id", Country),
        )
        for payload_key, field_name, model_cls in fk_map:
            if payload_key not in data:
                continue
            raw = data.get(payload_key)
            if raw is None or raw == "" or str(raw).strip().lower() in {"none", "null"}:
                updates[field_name] = None
                update_fields.append(field_name)
                continue
            try:
                pk = int(raw)
            except (TypeError, ValueError):
                return Response(
                    {"detail": f"╨Э╨╡╨║╨╛╤А╤А╨╡╨║╤В╨╜╤Л╨╣ {payload_key}"},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            if not model_cls.objects.filter(pk=pk).exists():
                return Response(
                    {"detail": f"{payload_key}={pk} ╨╜╨╡ ╨╜╨░╨╣╨┤╨╡╨╜"},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            updates[field_name] = pk
            update_fields.append(field_name)

        if "is_archived" in data:
            updates["is_archived"] = _coerce_bool(data.get("is_archived"))
            update_fields.append("is_archived")

        if "is_banned" in data:
            updates["is_banned"] = _coerce_bool(data.get("is_banned"))
            update_fields.append("is_banned")

        if not update_fields:
            return Response(
                {"detail": "╨г╨║╨░╨╢╨╕╤В╨╡ ╤Е╨╛╤В╤П ╨▒╤Л ╨╛╨┤╨╜╨╛ ╨┐╨╛╨╗╨╡ ╨┤╨╗╤П ╨╛╨▒╨╜╨╛╨▓╨╗╨╡╨╜╨╕╤П"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        qs = Account.objects.filter(id__in=id_ints)
        updated = qs.update(**updates)
        return Response({"updated": int(updated), "ids": id_ints, "fields": update_fields})

    @action(detail=False, methods=["post"], url_path="bulk-delete")
    def bulk_delete(self, request):
        """╨г╨┤╨░╨╗╨╕╤В╤М ╨▓╤Л╨▒╤А╨░╨╜╨╜╤Л╨╡ ╨░╨║╨║╨░╤Г╨╜╤В╤Л."""
        id_ints = _parse_account_ids_list(request.data.get("ids"))
        if id_ints is None:
            return Response(
                {"detail": "╨Я╨╡╤А╨╡╨┤╨░╨╣╤В╨╡ ╨╝╨░╤Б╤Б╨╕╨▓ ids"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if not id_ints:
            return Response(
                {"detail": "╨Т ids ╨┤╨╛╨╗╨╢╨╜╤Л ╨▒╤Л╤В╤М ╤З╨╕╤Б╨╗╨╛╨▓╤Л╨╡ ╨╕╨┤╨╡╨╜╤В╨╕╤Д╨╕╨║╨░╤В╨╛╤А╤Л ╨░╨║╨║╨░╤Г╨╜╤В╨╛╨▓"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        qs = Account.objects.filter(id__in=id_ints)
        matched = qs.count()
        qs.delete()
        return Response({"deleted": int(matched), "ids": id_ints})

    @action(detail=False, methods=["post"], url_path="refresh-link-clicks")
    def refresh_link_clicks(self, request):
        """╨Ю╨▒╨╜╨╛╨▓╨╕╤В╤М ╨┐╨╡╤А╨╡╤Е╨╛╨┤╤Л (Links) ╨┤╨╗╤П ╨▓╤Л╨▒╤А╨░╨╜╨╜╤Л╤Е ╨░╨║╨║╨░╤Г╨╜╤В╨╛╨▓ ╨▒╨╡╨╖ scrape ╨┐╨╗╨░╤В╤Д╨╛╤А╨╝."""
        ids = request.data.get("ids")
        if not isinstance(ids, list) or not ids:
            return Response(
                {"detail": "╨Я╨╡╤А╨╡╨┤╨░╨╣╤В╨╡ ╨╝╨░╤Б╤Б╨╕╨▓ ids"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        id_ints: list[int] = []
        for raw in ids:
            try:
                id_ints.append(int(raw))
            except (TypeError, ValueError):
                continue
        if not id_ints:
            return Response(
                {"detail": "╨Т ids ╨┤╨╛╨╗╨╢╨╜╤Л ╨▒╤Л╤В╤М ╤З╨╕╤Б╨╗╨╛╨▓╤Л╨╡ ╨╕╨┤╨╡╨╜╤В╨╕╤Д╨╕╨║╨░╤В╨╛╤А╤Л ╨░╨║╨║╨░╤Г╨╜╤В╨╛╨▓"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        by_id = {a.id: a for a in Account.objects.filter(id__in=id_ints)}
        ordered = [by_id[i] for i in id_ints if i in by_id]
        if not ordered:
            return Response({"detail": "╨Р╨║╨║╨░╤Г╨╜╤В╤Л ╨╜╨╡ ╨╜╨░╨╣╨┤╨╡╨╜╤Л"}, status=status.HTTP_404_NOT_FOUND)

        from integrations.links_client import LinksApiError, links_api_configured

        if not links_api_configured():
            return Response(
                {"detail": "Links API ╨╜╨╡ ╨╜╨░╤Б╤В╤А╨╛╨╡╨╜ (LINKS_API_URL / LINKS_API_TOKEN ╨▓ .env)"},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        try:
            result = _refresh_link_clicks_for_accounts(ordered, log_prefix="refresh_link_clicks")
            if result is None:
                return Response(
                    {"updated": 0, "changed": 0, "skipped": 0, "total": 0, "items": [], "errors": []},
                )
        except LinksApiError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)
        return Response(result)

    @action(detail=False, methods=["get"], url_path="export-snapshot")
    def export_snapshot(self, request):
        data = build_snapshot_csv()
        resp = HttpResponse(data, content_type="text/csv; charset=utf-8")
        resp["Content-Disposition"] = 'attachment; filename="dashboard-snapshot.csv"'
        return resp

    @action(
        detail=False,
        methods=["post"],
        url_path="import-snapshot",
        parser_classes=[MultiPartParser, JSONParser],
    )
    def import_snapshot(self, request):
        upload = request.FILES.get("file")
        # Fallback: allow direct raw CSV body (e.g. curl --data-binary @file.csv)
        # when multipart form is not used.
        if not upload and request.body:
            upload = SimpleUploadedFile(
                "snapshot.csv",
                request.body,
                content_type=request.content_type or "text/csv",
            )
        if not upload:
            return Response(
                {"detail": "╨Я╨╡╤А╨╡╨┤╨░╨╣╤В╨╡ ╤Д╨░╨╣╨╗ ╨▓ ╨┐╨╛╨╗╨╡ file"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            summary = import_snapshot_csv(upload)
        except OperationalError as e:
            if _is_deadlock_error(e):
                return Response(
                    {
                        "detail": (
                            "╨Ш╨╝╨┐╨╛╤А╤В ╨┐╤А╨╡╤А╨▓╨░╨╜ ╨╕╨╖тАС╨╖╨░ ╨▒╨╗╨╛╨║╨╕╤А╨╛╨▓╨║╨╕ ╨▓ ╨С╨Ф (deadlock), "
                            "╨╛╨▒╤Л╤З╨╜╨╛ ╤Н╤В╨╛ ╨┐╨░╤А╨░╨╗╨╗╨╡╨╗╤М╨╜╨╛╨╡ ╨╛╨▒╨╜╨╛╨▓╨╗╨╡╨╜╨╕╨╡ ╨░╨║╨║╨░╤Г╨╜╤В╨╛╨▓. "
                            "╨Я╨╛╨┤╨╛╨╢╨┤╨╕╤В╨╡ 10тАУ20 ╤Б ╨╕ ╨┐╨╛╨▓╤В╨╛╤А╨╕╤В╨╡ ╨╕╨╝╨┐╨╛╤А╤В."
                        ),
                    },
                    status=status.HTTP_409_CONFLICT,
                )
            return Response(
                {"detail": f"╨Ю╤И╨╕╨▒╨║╨░ ╤А╨░╨╖╨▒╨╛╤А╨░ CSV: {e}"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except Exception as e:
            return Response(
                {"detail": f"╨Ю╤И╨╕╨▒╨║╨░ ╤А╨░╨╖╨▒╨╛╤А╨░ CSV: {e}"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(summary)

    @action(detail=False, methods=["post"])
    def refresh_all(self, request):
        with _refresh_all_start_lock:
            auto_st = AutoRefreshState.get()
            rr = RefreshAllState.get()
            if auto_st.is_running or rr.is_running:
                return Response(
                    {"detail": "╨г╨╢╨╡ ╨▓╤Л╨┐╨╛╨╗╨╜╤П╨╡╤В╤Б╤П ╨░╨▓╤В╨╛╨╛╨▒╨╜╨╛╨▓╨╗╨╡╨╜╨╕╨╡, ╤Б╨▒╨╛╤А ╨▓╤Б╨╡╤Е ╨╕╨╗╨╕ ╨╝╨░╤Б╤Б╨╛╨▓╨╛╨╡ ╨╛╨▒╨╜╨╛╨▓╨╗╨╡╨╜╨╕╨╡."},
                    status=status.HTTP_409_CONFLICT,
                )
            download_csv = request.query_params.get("download_csv") in {"1", "true", "yes"}
            include_hidden = _coerce_bool(request.query_params.get("include_hidden"))
            include_hidden_platforms = include_hidden or _coerce_bool(
                request.query_params.get("include_hidden_platforms"),
            )
            include_hidden_profiles = include_hidden or _coerce_bool(
                request.query_params.get("include_hidden_profiles"),
            )
            include_archived_accounts = _coerce_bool(
                request.query_params.get("include_archived_accounts"),
            )
            include_banned_accounts = _coerce_bool(
                request.query_params.get("include_banned_accounts"),
            )
            rr.is_running = True
            rr.cancel_requested = False
            rr.total_accounts = 0
            rr.processed_accounts = 0
            rr.success_accounts = 0
            rr.failed_accounts = 0
            rr.current_account = ""
            rr.last_error = ""
            rr.started_at = timezone.now()
            rr.finished_at = None
            rr.run_detail = {}
            save_fields = [
                "is_running", "cancel_requested", "total_accounts", "processed_accounts",
                "success_accounts", "failed_accounts", "current_account", "last_error",
                "started_at", "finished_at", "run_detail", "updated_at",
                "last_report_csv", "last_report_generated_at",
            ]
            rr.last_report_csv = ""
            rr.last_report_generated_at = None
            rr.save(update_fields=save_fields)
        threading.Thread(
            target=_run_refresh_all_background,
            kwargs={
                "include_hidden_platforms": include_hidden_platforms,
                "include_hidden_profiles": include_hidden_profiles,
                "include_archived_accounts": include_archived_accounts,
                "include_banned_accounts": include_banned_accounts,
                "download_csv": download_csv,
            },
            daemon=True,
            name="refresh-all",
        ).start()
        return Response({"started": True, "download_csv": download_csv})

    @action(detail=True, methods=["get"])
    def posts(self, request, pk=None):
        account = self.get_object()
        today = timezone.localdate()
        period_days = _effective_account_delta_period_days(request)
        cutoff = today - datetime.timedelta(days=period_days)
        prev_post_snapshots = PostSnapshot.objects.filter(
            post=OuterRef("pk"),
            date__lte=cutoff,
        ).order_by("-date")
        qs = account.posts.annotate(
            _prev_view_count=Coalesce(
                Subquery(prev_post_snapshots.values("view_count")[:1]),
                Value(0),
                output_field=BigIntegerField(),
            ),
            _prev_like_count=Coalesce(
                Subquery(prev_post_snapshots.values("like_count")[:1]),
                Value(0),
                output_field=BigIntegerField(),
            ),
            _prev_comment_count=Coalesce(
                Subquery(prev_post_snapshots.values("comment_count")[:1]),
                Value(0),
                output_field=BigIntegerField(),
            ),
        ).annotate(
            _view_delta=F("view_count") - F("_prev_view_count"),
            _like_delta=F("like_count") - F("_prev_like_count"),
            _comment_delta=F("comment_count") - F("_prev_comment_count"),
        )
        ser_ctx = self.get_serializer_context()
        ser_ctx["parent_account_platform"] = account.platform
        return Response(PostSerializer(qs, many=True, context=ser_ctx).data)

    @action(detail=True, methods=["delete"], url_path=r"posts/(?P<post_id>[0-9]+)")
    def delete_post(self, request, pk=None, post_id=None):
        account = self.get_object()
        post = get_object_or_404(Post, pk=post_id, account=account)
        post.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class _DomainScopedCreateMixin:
    """╨Х╤Б╨╗╨╕ domain_id ╨╜╨╡ ╨┐╨╡╤А╨╡╨┤╨░╨╗╨╕, ╨░ ╨░╨┤╤А╨╡╤Б тАФ /reiz, ╨║╨╗╨░╨┤╤С╨╝ ╨▓ ╤В╨╡╨║╤Г╤Й╨╕╨╣ ╨┤╨╛╨╝╨╡╨╜.

    ╨п╨▓╨╜╤Л╨╣ ``domain_id: null`` (┬л╨С╨╡╨╖ ╨┤╨╛╨╝╨╡╨╜╨░┬╗ ╨▓ ╨╝╨╛╨┤╨░╨╗╨║╨╡) ╤Г╨▓╨░╨╢╨░╨╡╨╝: ╨╜╨╡ ╨┐╨╛╨┤╨╝╨╡╨╜╤П╨╡╨╝.
    """

    def perform_create(self, serializer):
        scope = domains.resolve(self.request)
        extra = {}
        if "domain" not in serializer.validated_data and scope.scoped:
            extra["domain"] = scope.domain
        serializer.save(**extra)


class OwnerViewSet(_DomainScopedCreateMixin, viewsets.ModelViewSet):
    serializer_class = OwnerSerializer

    def get_queryset(self):
        return domains.narrow(
            Owner.objects.annotate(
                account_count=Count(
                    "accounts",
                    filter=Q(accounts__is_archived=False, accounts__is_banned=False),
                ),
            ),
            domains.resolve(self.request),
        )

    def destroy(self, request, *args, **kwargs):
        owner = self.get_object()
        owner.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class AccountGroupViewSet(_DomainScopedCreateMixin, viewsets.ModelViewSet):
    serializer_class = AccountGroupSerializer

    def get_queryset(self):
        return domains.narrow(
            AccountGroup.objects.annotate(
                account_count=Count(
                    "accounts",
                    filter=Q(accounts__is_archived=False, accounts__is_banned=False),
                ),
            ),
            domains.resolve(self.request),
        )

    def destroy(self, request, *args, **kwargs):
        group = self.get_object()
        group.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class CountryViewSet(_DomainScopedCreateMixin, viewsets.ModelViewSet):
    serializer_class = CountrySerializer

    def get_queryset(self):
        return domains.narrow(
            Country.objects.annotate(
                account_count=Count(
                    "accounts",
                    filter=Q(accounts__is_archived=False, accounts__is_banned=False),
                ),
            ),
            domains.resolve(self.request),
        )

    def destroy(self, request, *args, **kwargs):
        country = self.get_object()
        country.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class ProfileViewSet(_DomainScopedCreateMixin, viewsets.ModelViewSet):
    serializer_class = ProfileSerializer

    def get_queryset(self):
        qs = Profile.objects.annotate(
            account_count=Count(
                "accounts",
                filter=Q(accounts__is_archived=False, accounts__is_banned=False),
            ),
        )
        include_hidden_profiles = _coerce_bool(self.request.query_params.get("include_hidden_profiles"))
        action = getattr(self, "action", "") or ""
        # ╨Я╨╛ ╤Б╨┐╨╕╤Б╨║╤Г ╤Б╨║╤А╤Л╤В╤Л╨╡ ╨╜╨╡ ╨┐╨╛╨║╨░╨╖╤Л╨▓╨░╨╡╨╝ ╨▒╨╡╨╖ ╤Д╨╗╨░╨│╨░; ╨┐╨╛ ID тАФ ╨▓╤Б╨╡╨│╨┤╨░ ╨╜╨░╤Е╨╛╨┤╨╕╨╝ ╨╖╨░╨┐╨╕╤Б╤М,
        # ╨╕╨╜╨░╤З╨╡ PATCH/DELETE ╤Б╨║╤А╤Л╤В╨╛╨│╨╛ ╨┐╤А╨╛╤Д╨╕╨╗╤П ╨┤╨░╤О╤В 404.
        detail_actions = {"retrieve", "update", "partial_update", "destroy"}
        if action in detail_actions:
            return qs
        if not include_hidden_profiles:
            qs = qs.filter(is_hidden=False)
        return domains.narrow(qs, domains.resolve(self.request))

    def destroy(self, request, *args, **kwargs):
        profile = self.get_object()
        delete_accounts = request.query_params.get("delete_accounts") == "true"
        if delete_accounts:
            profile.accounts.all().delete()
        # accounts without delete_accounts become profile=NULL via SET_NULL
        profile.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


@api_view(["GET"])
def platforms(request):
    hidden = _get_hidden_platforms()
    data = [{"value": v, "label": l, "hidden": v in hidden} for v, l in Platform.choices]
    return Response(data)


def _aggregate_yesterday_calendar_deltas(account_ids: list[int], today) -> tuple[int | None, int | None, int | None, int | None]:
    """╨б╤Г╨╝╨╝╨░ ╨┤╨╜╨╡╨▓╨╜╤Л╤Е ╨┤╨╡╨╗╤М╤В ╨╖╨░ ╨║╨░╨╗╨╡╨╜╨┤╨░╤А╨╜╤Л╨╣ ┬л╨▓╤З╨╡╤А╨░┬╗: snap(╨▓╤З╨╡╤А╨░) тИТ snap(╨┐╨╛╨╖╨░╨▓╤З╨╡╤А╨░) ╨┐╨╛ ╨║╨░╨╢╨┤╨╛╨╝╤Г ╨░╨║╨║╨░╤Г╨╜╤В╤Г.

    `today` тАФ ╨║╨░╨╗╨╡╨╜╨┤╨░╤А╨╜╤Л╨╣ ╨┤╨╡╨╜╤М ╨▓ ╨░╨║╤В╨╕╨▓╨╜╨╛╨╣ ╤В╨░╨╣╨╝╨╖╨╛╨╜╨╡ (╤Б╨╝. summary: timezone.localdate()), ╨┤╨╗╤П ╨┐╤А╨╛╨┤╨░╨║╤И╨╡╨╜╨░ Europe/Moscow.
    ╨Э╤Г╨╢╨╜╨░ ╨┤╨╗╤П ╨╝╨░╤Б╤И╤В╨░╨▒╨░ ╨╝╨╕╨╜╨╕-╨│╤А╨░╤Д╨╕╨║╨╛╨▓ ╨╜╨░ TV: ╨▓╤З╨╡╤А╨░╤И╨╜╨╕╨╣ ╨┐╤А╨╕╤А╨╛╤Б╤В = 50% ╨▓╤Л╤Б╨╛╤В╤Л ╨┐╤А╨╕ ╤А╨░╨▓╨╡╨╜╤Б╤В╨▓╨╡ ╤Б ╤Б╨╡╨│╨╛╨┤╨╜╤П╤И╨╜╨╕╨╝.
    """
    if not account_ids:
        return (None, None, None, None)
    yesterday = today - datetime.timedelta(days=1)
    before = today - datetime.timedelta(days=2)
    rows = AccountSnapshot.objects.filter(
        account_id__in=account_ids,
        date__in=(yesterday, before),
    ).values("account_id", "date", "follower_count", "like_count", "view_count", "post_count")
    by_acc: dict[int, dict] = {}
    for r in rows:
        aid = int(r["account_id"])
        by_acc.setdefault(aid, {})[r["date"]] = r
    d_follow = d_like = d_view = d_post = 0
    used = 0
    for aid in account_ids:
        sy = by_acc.get(aid, {}).get(yesterday)
        sb = by_acc.get(aid, {}).get(before)
        if sy is None or sb is None:
            continue
        used += 1
        d_follow += int(sy["follower_count"]) - int(sb["follower_count"])
        d_like += int(sy["like_count"]) - int(sb["like_count"])
        d_view += int(sy["view_count"]) - int(sb["view_count"])
        d_post += int(sy["post_count"]) - int(sb["post_count"])
    if used == 0:
        return (None, None, None, None)
    return (d_follow, d_like, d_view, d_post)


def _aggregate_prev_snapshot_pair_deltas(account_ids: list[int], today) -> tuple[int | None, int | None, int | None, int | None]:
    """╨б╤Г╨╝╨╝╨░ (╨┐╨╛╤Б╨╗╨╡╨┤╨╜╨╕╨╣ ╤Б╨╜╨╕╨╝╨╛╨║ тИТ ╨┐╤А╨╡╨┤╤Л╨┤╤Г╤Й╨╕╨╣) ╨┐╨╛ ╨║╨░╨╢╨┤╨╛╨╝╤Г ╨░╨║╨║╨░╤Г╨╜╤В╤Г, ╨╛╨▒╨░ ╤Б date < today.

    ╨Ш╤Б╨┐╨╛╨╗╤М╨╖╤Г╨╡╤В╤Б╤П, ╨║╨╛╨│╨┤╨░ ╨╜╨╡╤В ╨┐╨░╤А╤Л ╤Б╨╜╨╕╨╝╨║╨╛╨▓ ╤А╨╛╨▓╨╜╨╛ ╨╖╨░ ╨║╨░╨╗╨╡╨╜╨┤╨░╤А╨╜╤Л╨╣ ┬л╨▓╤З╨╡╤А╨░┬╗ ╨╕ ┬л╨┐╨╛╨╖╨░╨▓╤З╨╡╤А╨░┬╗, ╨╜╨╛ ╨╕╤Б╤В╨╛╤А╨╕╤П ╤Г╨╢╨╡ ╨╡╤Б╤В╤М
    (╨╜╨░╨┐╤А╨╕╨╝╨╡╤А, ╨┤╨╜╨╡╨▓╨╜╨╛╨╣ ╤Б╨╜╨╕╨╝╨╛╨║ ╨╖╨░ ┬л╨▓╤З╨╡╤А╨░┬╗ ╨╡╤Й╤С ╨╜╨╡ ╤Б╨╛╨╖╨┤╨░╨╜ ╨┤╨╛ ╤Б╨╗╨╡╨┤╤Г╤О╤Й╨╡╨│╨╛ ╨░╨▓╤В╨╛╨╛╨▒╨╜╨╛╨▓╨╗╨╡╨╜╨╕╤П). ╨Ш╨╜╤В╨╡╤А╨▓╨░╨╗ ╨╝╨╡╨╢╨┤╤Г ╨┤╨▓╤Г╨╝╤П ╨┤╨░╤В╨░╨╝╨╕
    ╨╝╨╛╨╢╨╡╤В ╨▒╤Л╤В╤М ╨▒╨╛╨╗╤М╤И╨╡ ╤Б╤Г╤В╨╛╨║ тАФ ╤Н╤В╨╛ ╨▓╤Б╤С ╤А╨░╨▓╨╜╨╛ ╨╛╤Б╨╝╤Л╤Б╨╗╨╡╨╜╨╜╨░╤П ╨╛╨┐╨╛╤А╨╜╨░╤П ╨┤╨╡╨╗╤М╤В╨░ ╨┤╨╗╤П ╨╝╨░╤Б╤И╤В╨░╨▒╨░ ╨│╤А╨░╤Д╨╕╨║╨░, ╨╜╨╡ ╨▓╤Л╨┤╤Г╨╝╨║╨░.
    """
    if not account_ids:
        return (None, None, None, None)
    rows = list(
        AccountSnapshot.objects.filter(account_id__in=account_ids, date__lt=today)
        .order_by("account_id", "-date")
        .values("account_id", "date", "follower_count", "like_count", "view_count", "post_count")
    )
    by_acc: dict[int, list[dict]] = {}
    for r in rows:
        aid = int(r["account_id"])
        lst = by_acc.setdefault(aid, [])
        if len(lst) >= 2:
            continue
        lst.append(r)
    d_follow = d_like = d_view = d_post = 0
    used = 0
    for lst in by_acc.values():
        if len(lst) < 2:
            continue
        s0, s1 = lst[0], lst[1]
        d_follow += int(s0["follower_count"]) - int(s1["follower_count"])
        d_like += int(s0["like_count"]) - int(s1["like_count"])
        d_view += int(s0["view_count"]) - int(s1["view_count"])
        d_post += int(s0["post_count"]) - int(s1["post_count"])
        used += 1
    if used == 0:
        return (None, None, None, None)
    return (d_follow, d_like, d_view, d_post)


def compute_summary(request) -> dict:
    """Aggregate stats + deltas across accounts (╤Г╤З╨╕╤В╤Л╨▓╨░╨╡╤В X-Domain / domain scope)."""
    today = timezone.localdate()
    include_hidden = _coerce_bool(request.query_params.get("include_hidden"))
    include_hidden_platforms = include_hidden or _coerce_bool(request.query_params.get("include_hidden_platforms"))
    include_hidden_profiles = include_hidden or _coerce_bool(request.query_params.get("include_hidden_profiles"))
    qs = Account.objects.prefetch_related("snapshots").all()
    qs = domains.narrow(qs, domains.resolve(request))
    qs = _apply_archived_filter(qs, request.query_params.get("archived"))
    qs = _apply_banned_filter(qs, request.query_params.get("banned"))
    qs = _apply_visibility_filters(
        qs,
        include_hidden_platforms=include_hidden_platforms,
        include_hidden_profiles=include_hidden_profiles,
    )
    accounts = list(qs)

    total = {
        "follower_count": 0,
        "like_count": 0,
        "view_count": 0,
        "post_count": 0,
        "link_click_count": 0,
    }
    snap_total = {
        "follower_count": 0,
        "like_count": 0,
        "view_count": 0,
        "post_count": 0,
        "link_click_count": 0,
    }
    by_platform: dict[str, dict] = {}

    period_days = _effective_account_delta_period_days(request)
    cutoff = today - datetime.timedelta(days=period_days)
    view_delta_sum = 0
    from .auto_refresh_pulse import clamp_platform_view_delta

    for acc in accounts:
        for key in total:
            total[key] += getattr(acc, key)

        snap = acc.snapshots.filter(date__lte=cutoff).order_by("-date").first()
        if snap:
            snap_total["follower_count"] += snap.follower_count
            snap_total["like_count"] += snap.like_count
            snap_total["view_count"] += snap.view_count
            snap_total["post_count"] += snap.post_count
            snap_total["link_click_count"] += snap.link_click_count
            dv = int(acc.view_count or 0) - int(snap.view_count or 0)
            dv = clamp_platform_view_delta(acc.platform, dv)
            view_delta_sum += dv
        else:
            # ╨Э╨╡╤В ╤Б╨╜╨╕╨╝╨║╨░ ╨╜╨╡ ╤Б╤В╨░╤А╤И╨╡ cutoff тАФ ╤Б╤З╨╕╤В╨░╨╡╨╝ baseline ╨╜╤Г╨╗╨╡╨▓╤Л╨╝: ╨▓╨╡╤Б╤М ╤В╨╡╨║╤Г╤Й╨╕╨╣ ╤Б╤З╤С╤В╤З╨╕╨║
            # ╤Г╤З╨░╤Б╤В╨▓╤Г╨╡╤В ╨▓ ╨┤╨╡╨╗╤М╤В╨╡ (╨░╨║╤В╤Г╨░╨╗╤М╨╜╨╛ ╨┤╨╗╤П ╨╛╨║╨╜╨░ 30╨┤ ╨╕ ┬л╨╝╨╛╨╗╨╛╨┤╤Л╤Е┬╗ ╨░╨║╨║╨░╤Г╨╜╤В╨╛╨▓).
            dv = int(acc.view_count or 0)
            view_delta_sum += dv

        p = acc.platform
        if p not in by_platform:
            by_platform[p] = {
                "platform": p,
                "platform_label": acc.get_platform_display(),
                "account_count": 0,
                "follower_count": 0,
                "like_count": 0,
                "view_count": 0,
                "post_count": 0,
                "link_click_count": 0,
                "view_delta": 0,
            }
        by_platform[p]["account_count"] += 1
        by_platform[p]["view_delta"] += dv
        for key in ("follower_count", "like_count", "view_count", "post_count", "link_click_count"):
            by_platform[p][key] += getattr(acc, key)

    account_ids = [int(a.pk) for a in accounts]
    y_follow, y_like, y_view, y_post = _aggregate_yesterday_calendar_deltas(account_ids, today)
    if y_follow is None:
        y_follow, y_like, y_view, y_post = _aggregate_prev_snapshot_pair_deltas(account_ids, today)

    return {
        "account_count": len(accounts),
        "follower_count": total["follower_count"],
        "like_count": total["like_count"],
        "view_count": total["view_count"],
        "post_count": total["post_count"],
        "link_click_count": total["link_click_count"],
        "follower_delta": total["follower_count"] - snap_total["follower_count"] if accounts else None,
        "like_delta": total["like_count"] - snap_total["like_count"] if accounts else None,
        "view_delta": view_delta_sum if accounts else None,
        "post_delta": total["post_count"] - snap_total["post_count"] if accounts else None,
        "link_click_delta": total["link_click_count"] - snap_total["link_click_count"] if accounts else None,
        "yesterday_follower_delta": y_follow,
        "yesterday_like_delta": y_like,
        "yesterday_view_delta": y_view,
        "yesterday_post_delta": y_post,
        "by_platform": list(by_platform.values()),
    }


@api_view(["GET"])
def summary(request):
    """Aggregate stats + deltas across accounts, grouped by platform."""
    return Response(compute_summary(request))


def _schedule_db_error_response(exc: BaseException) -> Response:
    logger.warning("schedule/auto-refresh DB error: %s", exc)
    return Response(
        {
            "detail": (
                "╨Ю╤И╨╕╨▒╨║╨░ ╨▒╨░╨╖╤Л ╨┤╨░╨╜╨╜╤Л╤Е (╨░╨▓╤В╨╛╨╛╨▒╨╜╨╛╨▓╨╗╨╡╨╜╨╕╨╡ / ╤А╨░╤Б╨┐╨╕╤Б╨░╨╜╨╕╨╡). "
                "╨Э╨░ ╤Б╨╡╤А╨▓╨╡╤А╨╡ ╨▓╤Л╨┐╨╛╨╗╨╜╨╕╤В╨╡ ┬лpython manage.py migrate┬╗ ╨▓ ╨║╨░╤В╨░╨╗╨╛╨│╨╡ backend ╨╕ ╨┐╨╡╤А╨╡╨╖╨░╨┐╤Г╤Б╤В╨╕╤В╨╡ ╨┐╤А╨╛╤Ж╨╡╤Б╤Б."
            ),
        },
        status=status.HTTP_503_SERVICE_UNAVAILABLE,
    )


def _telegram_bot_configured() -> bool:
    from .telegram_report import telegram_bot_configured

    return telegram_bot_configured()


def _telegram_default_chat_id() -> str:
    from django.conf import settings

    return (getattr(settings, "TELEGRAM_AUTO_REFRESH_CHAT_ID", None) or "").strip()


def _schedule_telegram_chat_ids(config) -> list[str]:
    from .telegram_chat_ids import telegram_chat_ids_from_config

    return telegram_chat_ids_from_config(config)


def _schedule_telegram_chat_id_legacy(config) -> str:
    ids = _schedule_telegram_chat_ids(config)
    if ids:
        return ids[0]
    return (getattr(config, "auto_refresh_telegram_chat_id", None) or "").strip()


def _apply_schedule_telegram_chat_ids(config, chat_ids: list[str]) -> None:
    from .telegram_chat_ids import normalize_telegram_chat_ids

    ids = normalize_telegram_chat_ids(chat_ids)
    config.auto_refresh_telegram_chat_ids = ids
    config.auto_refresh_telegram_chat_id = ids[0] if ids else ""


def _schedule_to_dict(config) -> dict:
    from .auto_refresh_scope import (
        normalize_auto_refresh_platforms,
        normalize_auto_refresh_profile_ids,
        normalize_auto_refresh_owner_ids,
        normalize_auto_refresh_group_ids,
        normalize_auto_refresh_country_ids,
        normalize_auto_refresh_domain_ids,
        normalize_schedule_times,
    )

    return {
        "enabled": config.enabled,
        "mode": config.mode,
        "interval_hours": config.interval_hours,
        "skip_recent_hours": config.skip_recent_hours,
        "refresh_warm_enabled": bool(getattr(config, "refresh_warm_enabled", True)),
        "auto_refresh_platforms": normalize_auto_refresh_platforms(
            getattr(config, "auto_refresh_platforms", None),
        ),
        "auto_refresh_profile_ids": normalize_auto_refresh_profile_ids(
            getattr(config, "auto_refresh_profile_ids", None),
        ),
        "auto_refresh_owner_ids": normalize_auto_refresh_owner_ids(
            getattr(config, "auto_refresh_owner_ids", None),
        ),
        "auto_refresh_group_ids": normalize_auto_refresh_group_ids(
            getattr(config, "auto_refresh_group_ids", None),
        ),
        "auto_refresh_country_ids": normalize_auto_refresh_country_ids(
            getattr(config, "auto_refresh_country_ids", None),
        ),
        "auto_refresh_domain_ids": normalize_auto_refresh_domain_ids(
            getattr(config, "auto_refresh_domain_ids", None),
        ),
        "auto_refresh_csv_report": True,
        "auto_refresh_telegram_enabled": bool(
            getattr(config, "auto_refresh_telegram_enabled", False),
        ),
        "auto_refresh_telegram_chat_ids": _schedule_telegram_chat_ids(config),
        "auto_refresh_telegram_chat_id": _schedule_telegram_chat_id_legacy(config),
        "telegram_bot_configured": _telegram_bot_configured(),
        "telegram_chat_configured": bool(
            _schedule_telegram_chat_ids(config) or _telegram_default_chat_id()
        ),
        "include_hidden_platform_accounts": bool(
            getattr(config, "include_hidden_platform_accounts", False),
        ),
        "include_hidden_profile_accounts": bool(
            getattr(config, "include_hidden_profile_accounts", False),
        ),
        "include_unavailable_accounts": bool(
            getattr(config, "include_unavailable_accounts", False),
        ),
        "include_archived_accounts": bool(
            getattr(config, "include_archived_accounts", False),
        ),
        "include_banned_accounts": bool(
            getattr(config, "include_banned_accounts", False),
        ),
        "account_delta_period_days": (
            d if (d := int(getattr(config, "account_delta_period_days", 1) or 1)) in (1, 7, 30) else 1
        ),
        "times": normalize_schedule_times(config.times),
    }


def _coerce_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    s = str(value).strip().lower()
    if s in {"1", "true", "yes", "on"}:
        return True
    if s in {"0", "false", "no", "off"}:
        return False
    return bool(value)


def _parse_account_ids_list(raw) -> list[int] | None:
    """None тАФ ╨╜╨╡╤В ╨╝╨░╤Б╤Б╨╕╨▓╨░; [] тАФ ╨╝╨░╤Б╤Б╨╕╨▓ ╨▒╨╡╨╖ ╨▓╨░╨╗╨╕╨┤╨╜╤Л╤Е id."""
    if not isinstance(raw, list):
        return None
    out: list[int] = []
    seen: set[int] = set()
    for item in raw:
        try:
            n = int(item)
        except (TypeError, ValueError):
            continue
        if n not in seen:
            seen.add(n)
            out.append(n)
    return out


@api_view(["GET", "POST"])
def global_visibility(request):
    """
    Global visibility settings shared by all users:
    - hidden_platforms (list[str])
    - hidden_profile_ids (derived from Profile.is_hidden)
    """
    cfg = GlobalVisibilityConfig.get()
    if request.method == "POST":
        data = request.data or {}
        if "hidden_platforms" in data and isinstance(data["hidden_platforms"], list):
            allowed = {v for v, _ in Platform.choices}
            normalized = []
            for raw in data["hidden_platforms"]:
                v = str(raw).strip().lower()
                if v in allowed and v not in normalized:
                    normalized.append(v)
            cfg.hidden_platforms = normalized
            cfg.save(update_fields=["hidden_platforms"])
        if "hidden_profile_ids" in data and isinstance(data["hidden_profile_ids"], list):
            ids = []
            for raw in data["hidden_profile_ids"]:
                try:
                    ids.append(int(raw))
                except (TypeError, ValueError):
                    continue
            keep = set(ids)
            Profile.objects.exclude(id__in=keep).update(is_hidden=False)
            if keep:
                Profile.objects.filter(id__in=keep).update(is_hidden=True)

    hidden_platforms = list(getattr(cfg, "hidden_platforms", None) or [])
    hidden_profile_ids = list(
        Profile.objects.filter(is_hidden=True).values_list("id", flat=True),
    )
    return Response({
        "hidden_platforms": hidden_platforms,
        "hidden_profile_ids": hidden_profile_ids,
    })


def _get_hidden_platforms() -> set[str]:
    try:
        cfg = GlobalVisibilityConfig.get()
        raw = getattr(cfg, "hidden_platforms", None) or []
        return {str(v).strip().lower() for v in raw if str(v).strip()}
    except Exception:
        return set()


def _apply_archived_filter(qs, archived_param):
    """
    archived query param:
      - omitted / 0 / false / active тЖТ ╤В╨╛╨╗╤М╨║╨╛ ╨░╨║╤В╤Г╨░╨╗╤М╨╜╤Л╨╡ (is_archived=False)
      - 1 / true / archived тЖТ ╤В╨╛╨╗╤М╨║╨╛ ╨░╤А╤Е╨╕╨▓
      - all / both тЖТ ╨▒╨╡╨╖ ╤Д╨╕╨╗╤М╤В╤А╨░
    """
    raw = str(archived_param or "").strip().lower()
    if raw in ("all", "both", "any"):
        return qs
    if raw in ("1", "true", "yes", "archived"):
        return qs.filter(is_archived=True)
    return qs.filter(is_archived=False)


def _apply_banned_filter(qs, banned_param):
    """
    banned query param:
      - omitted / 0 / false / active тЖТ ╤В╨╛╨╗╤М╨║╨╛ ╨╜╨╡ ╨▓ ╨▒╨░╨╜╨╡ (is_banned=False)
      - 1 / true / banned тЖТ ╤В╨╛╨╗╤М╨║╨╛ ╨▒╨░╨╜
      - all / both тЖТ ╨▒╨╡╨╖ ╤Д╨╕╨╗╤М╤В╤А╨░
    """
    raw = str(banned_param or "").strip().lower()
    if raw in ("all", "both", "any"):
        return qs
    if raw in ("1", "true", "yes", "banned"):
        return qs.filter(is_banned=True)
    return qs.filter(is_banned=False)


def _apply_visibility_filters(
    qs,
    *,
    include_hidden_platforms: bool = False,
    include_hidden_profiles: bool = False,
):
    if not include_hidden_platforms:
        hidden_platforms = _get_hidden_platforms()
        if hidden_platforms:
            qs = qs.exclude(platform__in=hidden_platforms)
    if not include_hidden_profiles:
        qs = qs.exclude(profile__is_hidden=True)
    return qs


@api_view(["GET", "POST"])
def refresh_schedule(request):
    """Get or update the auto-refresh schedule config."""
    from .apps import get_scheduler, sync_schedule_from_db

    try:
        config = RefreshScheduleConfig.get()

        if request.method == "GET":
            return Response(_schedule_to_dict(config))

        data = request.data
        if "enabled" in data:
            config.enabled = _coerce_bool(data["enabled"])
        if "mode" in data and data["mode"] in ("interval", "times"):
            config.mode = data["mode"]
        if "interval_hours" in data:
            config.interval_hours = max(1, min(24, int(data["interval_hours"])))
        if "skip_recent_hours" in data:
            config.skip_recent_hours = max(0, min(168, int(data["skip_recent_hours"])))
        if "refresh_warm_enabled" in data:
            config.refresh_warm_enabled = _coerce_bool(data["refresh_warm_enabled"])
        config.auto_refresh_csv_report = True
        if "auto_refresh_telegram_enabled" in data:
            config.auto_refresh_telegram_enabled = _coerce_bool(
                data["auto_refresh_telegram_enabled"],
            )
        if "auto_refresh_telegram_chat_ids" in data:
            _apply_schedule_telegram_chat_ids(
                config,
                data.get("auto_refresh_telegram_chat_ids"),
            )
        elif "auto_refresh_telegram_chat_id" in data:
            legacy = str(data.get("auto_refresh_telegram_chat_id") or "").strip()[:32]
            _apply_schedule_telegram_chat_ids(config, [legacy] if legacy else [])
        if "include_hidden_platform_accounts" in data:
            config.include_hidden_platform_accounts = _coerce_bool(data["include_hidden_platform_accounts"])
        if "include_hidden_profile_accounts" in data:
            config.include_hidden_profile_accounts = _coerce_bool(data["include_hidden_profile_accounts"])
        if "include_unavailable_accounts" in data:
            config.include_unavailable_accounts = _coerce_bool(data["include_unavailable_accounts"])
        if "include_archived_accounts" in data:
            config.include_archived_accounts = _coerce_bool(data["include_archived_accounts"])
        if "include_banned_accounts" in data:
            config.include_banned_accounts = _coerce_bool(data["include_banned_accounts"])
        if "auto_refresh_platforms" in data:
            from .auto_refresh_scope import normalize_auto_refresh_platforms

            config.auto_refresh_platforms = normalize_auto_refresh_platforms(
                data["auto_refresh_platforms"],
            )
        if "auto_refresh_profile_ids" in data:
            from .auto_refresh_scope import normalize_auto_refresh_profile_ids

            config.auto_refresh_profile_ids = normalize_auto_refresh_profile_ids(
                data["auto_refresh_profile_ids"],
            )
        if "auto_refresh_owner_ids" in data:
            from .auto_refresh_scope import normalize_auto_refresh_owner_ids

            config.auto_refresh_owner_ids = normalize_auto_refresh_owner_ids(
                data["auto_refresh_owner_ids"],
            )
        if "auto_refresh_group_ids" in data:
            from .auto_refresh_scope import normalize_auto_refresh_group_ids

            config.auto_refresh_group_ids = normalize_auto_refresh_group_ids(
                data["auto_refresh_group_ids"],
            )
        if "auto_refresh_country_ids" in data:
            from .auto_refresh_scope import normalize_auto_refresh_country_ids

            config.auto_refresh_country_ids = normalize_auto_refresh_country_ids(
                data["auto_refresh_country_ids"],
            )
        if "auto_refresh_domain_ids" in data:
            from .auto_refresh_scope import normalize_auto_refresh_domain_ids

            config.auto_refresh_domain_ids = normalize_auto_refresh_domain_ids(
                data["auto_refresh_domain_ids"],
            )
        if "times" in data and isinstance(data["times"], list):
            from .auto_refresh_scope import normalize_schedule_times

            config.times = normalize_schedule_times(data["times"])
        if "account_delta_period_days" in data:
            raw = int(data["account_delta_period_days"])
            config.account_delta_period_days = raw if raw in (1, 7, 30) else 1
        config.save()

        sched = get_scheduler()
        if sched is not None:
            sync_schedule_from_db(force=True)
        else:
            print(
                "[scheduler] POST /schedule/: ╨┐╨╗╨░╨╜╨╕╤А╨╛╨▓╤Й╨╕╨║ ╨╜╨╡ ╨╖╨░╨┐╤Г╤Й╨╡╨╜ тАФ "
                "╤Б╨╗╨╛╤В╤Л ╨┐╨╛ ╨▓╤А╨╡╨╝╨╡╨╜╨╕ ╨╜╨╡ ╤Б╤А╨░╨▒╨╛╤В╨░╤О╤В. ╨Я╨╡╤А╨╡╨╖╨░╨┐╤Г╤Б╤В╨╕╤В╨╡ runserver.",
                file=sys.stderr,
                flush=True,
            )

        return Response(_schedule_to_dict(config))
    except (ProgrammingError, OperationalError) as exc:
        return _schedule_db_error_response(exc)


@api_view(["POST"])
def auto_refresh_telegram_test(request):
    """╨Я╤А╨╛╨▓╨╡╤А╨║╨░ TELEGRAM_BOT_TOKEN ╨╕ chat_id (╤В╨╡╤Б╤В╨╛╨▓╨╛╨╡ ╤Б╨╛╨╛╨▒╤Й╨╡╨╜╨╕╨╡)."""
    try:
        from .models import RefreshScheduleConfig
        from .telegram_report import send_telegram_test_message

        from .telegram_chat_ids import normalize_telegram_chat_ids

        config = RefreshScheduleConfig.get()
        data = request.data if isinstance(request.data, dict) else {}
        chat_ids_raw = data.get("chat_ids")
        chat_ids = (
            normalize_telegram_chat_ids(chat_ids_raw)
            if isinstance(chat_ids_raw, list)
            else None
        )
        chat_id = str(data.get("chat_id") or "").strip() or None
        send_telegram_test_message(config=config, chat_id=chat_id, chat_ids=chat_ids)
        n = len(chat_ids) if chat_ids else 1
        detail = (
            f"╨б╨╛╨╛╨▒╤Й╨╡╨╜╨╕╨╡ ╨╛╤В╨┐╤А╨░╨▓╨╗╨╡╨╜╨╛ ╨▓ {n} ╤З╨░╤В(╨╛╨▓) Telegram."
            if chat_ids and len(chat_ids) > 1
            else "╨б╨╛╨╛╨▒╤Й╨╡╨╜╨╕╨╡ ╨╛╤В╨┐╤А╨░╨▓╨╗╨╡╨╜╨╛ ╨▓ Telegram."
        )
        return Response({"ok": True, "detail": detail})
    except Exception as exc:
        return Response(
            {"ok": False, "detail": str(exc)},
            status=status.HTTP_400_BAD_REQUEST,
        )


#: ╨з╨░╤Б ╨┐╨╛ ╨╝╨╡╤Б╤В╨╜╨╛╨╝╤Г ╨▓╤А╨╡╨╝╨╡╨╜╨╕ (Europe/Moscow), ╨╜╨░ ╨║╨╛╤В╨╛╤А╨╛╨╝ ╤А╨╡╨╢╨╡╤В╤Б╤П ┬л╨┤╨╡╨╜╤М┬╗ ╤Б╤З╤С╤В╤З╨╕╨║╨░.
#: ╨б 10:00 ╨┤╨╛ 20:00 ╤Д╤А╨╛╨╜╤В ╤А╨░╤Б╤В╤П╨│╨╕╨▓╨░╨╡╤В ╨┐╤А╨╕╤А╨╛╤Б╤В prevтЖТnow; ╨┐╨╛╤Б╨╗╨╡ 20:00 ╤Ж╨╕╤Д╤А╨░
#: ╨╖╨░╨╝╨╛╤А╨╛╨╢╨╡╨╜╨░ ╨┤╨╛ ╤Б╨╗╨╡╨┤╤Г╤О╤Й╨╕╤Е 10:00.
VIEWS_ANCHOR_HOUR = 10
VIEWS_GROWTH_END_HOUR = 20


@api_view(["GET"])
def domain_list(request):
    """╨Ф╨╛╨╝╨╡╨╜╤Л ╨╕ ╤В╨╛, ╨║╨░╨║╨╛╨╣ ╨╕╨╖ ╨╜╨╕╤Е ╨▓╤Л╨▒╤А╨░╨╜ ╤В╨╡╨║╤Г╤Й╨╕╨╝ ╨░╨┤╤А╨╡╤Б╨╛╨╝.

    ╨д╤А╨╛╨╜╤В ╨┐╨╛ ╤Н╤В╨╛╨╝╤Г ╨╛╤В╨▓╨╡╤В╤Г ╨┐╨╛╨╜╨╕╨╝╨░╨╡╤В, ╨│╨┤╨╡ ╨╛╨╜ ╨╜╨░╤Е╨╛╨┤╨╕╤В╤Б╤П, ╨╕ ╨┐╨╛╨┤╨┐╨╕╤Б╤Л╨▓╨░╨╡╤В ╤Н╨║╤А╨░╨╜.
    ``current`` ╨╝╨╛╨╢╨╡╤В ╨▒╤Л╤В╤М ╨┐╤Г╤Б╤В╤Л╨╝ тАФ ╨╖╨╜╨░╤З╨╕╤В, ╨░╨┤╤А╨╡╤Б ╨▒╨╡╨╖ ╨┤╨╛╨╝╨╡╨╜╨░ ╨╕ ╨┐╨╛╨║╨░╨╖╤Л╨▓╨░╨╡╨╝ ╨▓╤Б╤С.
    """
    scope = domains.resolve(request)
    rows = [
        {"id": d.id, "slug": d.slug, "name": d.name, "color": d.color,
         "accounts": (
             Account.objects.filter(domains.account_q(domains.DomainScope(domain=d))).count()
             if domains.is_topics(domains.DomainScope(domain=d)) else d.accounts.count()
         )}
        for d in Domain.objects.filter(is_active=True)
    ]
    return Response({
        "domains": rows,
        "aggregate_slug": domains.AGGREGATE_DOMAIN_SLUG,
        "current": scope.domain.slug if scope.domain else None,
        "aggregate": scope.aggregate,
        # ╨Ъ╤Г╤Б╨╛╨║ ╨░╨┤╤А╨╡╤Б╨░ ╨▒╤Л╨╗, ╨░ ╨┤╨╛╨╝╨╡╨╜╨░ ╤В╨░╨║╨╛╨│╨╛ ╨╜╨╡╤В тАФ ╤Д╤А╨╛╨╜╤В╤Г ╤Б╤В╨╛╨╕╤В ╤Б╨║╨░╨╖╨░╤В╤М ╨╛╨▒ ╤Н╤В╨╛╨╝
        # ╨▓╤Б╨╗╤Г╤Е, ╨░ ╨╜╨╡ ╨╝╨╛╨╗╤З╨░ ╨┐╨╛╨║╨░╨╖╤Л╨▓╨░╤В╤М ╤З╤Г╨╢╨╛╨╣ ╨╜╨░╨▒╨╛╤А.
        "unknown": scope.unknown,
        "unassigned_accounts": Account.objects.filter(domain__isnull=True).count(),
    })


#: ╨Я╨╛╨║╨░╨╖╨░╤В╨╡╨╗╨╕ ╨╢╨╕╨▓╨╛╨│╨╛ ╤Б╤З╤С╤В╤З╨╕╨║╨░: ╨║╨╗╤О╤З ╨┤╨╗╤П ╤Д╤А╨╛╨╜╤В╨░ -> ╨┐╨╛╨╗╨╡ ╨▓ AccountSnapshot.
VC_METRICS = {
    "views": "view_count",
    "followers": "follower_count",
    "likes": "like_count",
    "posts": "post_count",
    "clicks": "link_click_count",
}


def _totals_as_of(day, scope=None):
    """╨Ш╤В╨╛╨│╨╕ ╨╜╨░ ╨║╨╛╨╜╨╡╤Ж ╨┤╨╜╤П ``day`` тАФ ╨┐╨╛ ╨┐╨╛╤Б╨╗╨╡╨┤╨╜╨╡╨╝╤Г ╤Б╨╜╨╕╨╝╨║╤Г ╨║╨░╨╢╨┤╨╛╨│╨╛ ╨░╨║╨║╨░╤Г╨╜╤В╨░.

    ╨Я╤А╨╛╤Б╤В╨╛ ╨┐╤А╨╛╤Б╤Г╨╝╨╝╨╕╤А╨╛╨▓╨░╤В╤М ``AccountSnapshot`` ╨╖╨░ ╨┤╨░╤В╤Г ╨╜╨╡╨╗╤М╨╖╤П: ╤Б╤В╤А╨╛╨║╨╕ ╤В╨░╨╝ ╤В╨╛╨╗╤М╨║╨╛
    ╨┐╨╛ ╨╛╨▒╨╜╨╛╨▓╨╗╤С╨╜╨╜╤Л╨╝ ╨▓ ╤Н╤В╨╛╤В ╨┤╨╡╨╜╤М ╨░╨║╨║╨░╤Г╨╜╤В╨░╨╝, ╨┐╨╛╤Н╤В╨╛╨╝╤Г ╤Б╤Г╨╝╨╝╨░ ╨╖╨░ ╨┤╨╡╨╜╤М тАФ ╤Н╤В╨╛ ╤Б╤Г╨╝╨╝╨░ ╨┐╨╛
    ╤Б╨╗╤Г╤З╨░╨╣╨╜╨╛╨╝╤Г ╨┐╨╛╨┤╨╝╨╜╨╛╨╢╨╡╤Б╤В╨▓╤Г (╨▓ ╨▒╨░╨╖╨╡ ╨▓╤Б╤В╤А╨╡╤З╨░╨╡╤В╤Б╤П ┬л╨┤╨╡╨╗╤М╤В╨░┬╗ тИТ884 638). ╨С╨╡╤А╤С╨╝ ╨┐╨╛
    ╨║╨░╨╢╨┤╨╛╨╝╤Г ╨░╨║╨║╨░╤Г╨╜╤В╤Г ╨┐╨╛╤Б╨╗╨╡╨┤╨╜╨╕╨╣ ╤Б╨╜╨╕╨╝╨╛╨║ ╨╜╨╡ ╨┐╨╛╨╖╨╢╨╡ ╨┤╨░╤В╤Л ╨╕ ╤Б╨║╨╗╨░╨┤╤Л╨▓╨░╨╡╨╝: ╤Н╤В╨╛ ╨╕ ╨╡╤Б╤В╤М
    ╨┐╨╛╤Б╨╗╨╡╨┤╨╜╨╡╨╡ ╨╕╨╖╨▓╨╡╤Б╤В╨╜╨╛╨╡ ╤Б╨╛╤Б╤В╨╛╤П╨╜╨╕╨╡ ╤Б╨╡╤В╨╕ ╨╜╨░ ╤В╨╛╤В ╨╝╨╛╨╝╨╡╨╜╤В.

    ╨Я╤А╨╛╨▓╨╡╤А╨╡╨╜╨╛ ╤Б╨▓╨╡╤А╨║╨╛╨╣: ╨┤╨╗╤П ╨┐╤А╨╛╤Б╨╝╨╛╤В╤А╨╛╨▓ ╤А╨╡╨╖╤Г╨╗╤М╤В╨░╤В ╤Б╨╛╨▓╨┐╨░╨┤╨░╨╡╤В ╤Б
    ``AutoRefreshPoint.view_count_total``, ╨│╨┤╨╡ ╨╜╨░╤Б╤В╨╛╤П╤Й╨╕╨╣ ╤Б╨╡╤В╨╡╨▓╨╛╨╣ ╨╕╤В╨╛╨│ ╤Г╨╢╨╡ ╨╡╤Б╤В╤М.

    ``scope`` ╤Б╤Г╨╢╨░╨╡╤В ╤Б╤З╤С╤В ╨┤╨╛ ╨┤╨╛╨╝╨╡╨╜╨░: ╨╕╨╜╨░╤З╨╡ ╨╜╨░ /reiz ╤Б ╨╜╤Г╨╗╤С╨╝ ╨░╨║╨║╨░╤Г╨╜╤В╨╛╨▓ ╤Б╤З╤С╤В╤З╨╕╨║
    ╨┐╨╛╨║╨░╨╖╤Л╨▓╨░╨╗ ╨▒╤Л ╨╕╤В╨╛╨│╨╕ ╨▓╤Б╨╡╨╣ ╤Б╨╡╤В╨╕ тАФ ╤З╨╕╤Б╨╗╨░, ╨║╨╛╤В╨╛╤А╤Л╨╝ ╨╜╨░ ╤Н╤В╨╛╨╝ ╤Н╨║╤А╨░╨╜╨╡ ╨▓╨╖╤П╤В╤М╤Б╤П
    ╨╜╨╡╨╛╤В╨║╤Г╨┤╨░.
    """
    qs = AccountSnapshot.objects.filter(date__lte=day)
    if scope is not None:
        if scope.unknown:
            return (None, 0)      # ╤Г╤Б╤В╨░╤А╨╡╨▓╤И╨░╤П ╤Б╤Б╤Л╨╗╨║╨░ тАФ ╤Б╤З╨╕╤В╨░╤В╤М ╨╜╨╡╤З╨╡╨│╨╛
        if scope.scoped:
            qs = qs.filter(domains.account_q(scope, "account__"))
    rows = (
        qs.order_by("account_id", "-date")
        .distinct("account_id")
        .values("account_id", *VC_METRICS.values())
    )
    out = {k: 0 for k in VC_METRICS}
    seen = 0
    for r in rows:
        seen += 1
        for key, field in VC_METRICS.items():
            out[key] += int(r[field] or 0)
    return (out, seen) if seen else (None, 0)


def _views_total_at(moment, scope=None):
    """╨б╤Г╨╝╨╝╨░╤А╨╜╤Л╨╡ ╨┐╤А╨╛╤Б╨╝╨╛╤В╤А╤Л ╤Б╨╡╤В╨╕ ╨╜╨░ ╨╝╨╛╨╝╨╡╨╜╤В ``moment`` тАФ ╨┐╨╛╤Б╨╗╨╡╨┤╨╜╤П╤П ╤В╨╛╤З╨║╨░ ╨╜╨╡ ╨┐╨╛╨╖╨╢╨╡ ╨╜╨╡╨│╨╛.

    ╨Ф╨╗╤П ╨┐╤А╨╛╤Б╨╝╨╛╤В╤А╨╛╨▓ ╨╕╤Б╤В╨╛╤З╨╜╨╕╨║ ╤В╨╛╤З╨╜╨╡╨╡, ╤З╨╡╨╝ ╤Б╨╜╨╕╨╝╨║╨╕: ``AutoRefreshPoint`` ╨┐╨╕╤И╨╡╤В╤Б╤П ╤Б╨╛
    ╨▓╤А╨╡╨╝╨╡╨╜╨╡╨╝, ╨┐╨╛╤Н╤В╨╛╨╝╤Г ┬л╨╜╨░ 10:00┬╗ ╨╖╨┤╨╡╤Б╤М ╨▒╤Г╨║╨▓╨░╨╗╤М╨╜╨╛ ╨╜╨░ 10:00, ╨░ ╨╜╨╡ ┬л╨╜╨░ ╨║╨╛╨╜╨╡╤Ж ╨┤╨╜╤П┬╗.
    ╨г ╨╛╤Б╤В╨░╨╗╤М╨╜╤Л╤Е ╨┐╨╛╨║╨░╨╖╨░╤В╨╡╨╗╨╡╨╣ ╤В╨░╨║╨╛╨│╨╛ ╤А╤П╨┤╨░ ╨╜╨╡╤В тАФ ╨╛╨╜╨╕ ╨╕╨┤╤Г╤В ╤З╨╡╤А╨╡╨╖ ``_totals_as_of``.

    ╨Т╨╛╨╖╨▓╤А╨░╤Й╨░╨╡╤В ``(total, measured_at)`` ╨╕╨╗╨╕ ``(None, None)``, ╨╡╤Б╨╗╨╕ ╤В╨╛╤З╨╡╨║ ╨┤╨╛
    ╤Н╤В╨╛╨│╨╛ ╨╝╨╛╨╝╨╡╨╜╤В╨░ ╨╡╤Й╤С ╨╜╨╡╤В.
    """
    point = (
        AutoRefreshPoint.objects.filter(measured_at__lte=moment)
        .order_by("-measured_at")
        .values("view_count_total", "domain_totals", "measured_at")
        .first()
    )
    if not point:
        return (None, None)
    if scope is not None and scope.scoped:
        # У точек, записанных до domain_totals, домена в словаре нет — отдаём
        # None, чтобы вызывающий упал на снимки, а не показал домену итог сети.
        totals = point.get("domain_totals") or {}
        key = str(scope.domain.id)
        if key not in totals:
            return (None, None)
        return (int(totals[key] or 0), point["measured_at"])
    return (point["view_count_total"], point["measured_at"])


def _views_by_account_at(moment):
    """Просмотры по аккаунтам на момент ``moment`` — из последней точки не позже.

    Нужно фронту, чтобы считать прирост произвольного среза: фильтры рельса
    комбинируются, а по суммам по доменам или площадкам сочетание не собрать.
    Пусто, если у точки разбивки нет (записана до появления поля).
    """
    point = (
        AutoRefreshPoint.objects.filter(measured_at__lte=moment)
        .order_by("-measured_at")
        .values("account_totals")
        .first()
    )
    if not point:
        return {}
    return point.get("account_totals") or {}


def _account_growth_between(prev_moment, now_moment) -> dict:
    """Прирост просмотров по аккаунтам между двумя моментами.

    Отдаём только ненулевые: на 1360 аккаунтов растут единицы, и в ответе это
    десятки строк вместо полутора тысяч. Отрицательные (аккаунт удалили или
    площадка пересчитала) не отматываем назад — как и в ``pair``.
    """
    prev = _views_by_account_at(prev_moment)
    now = _views_by_account_at(now_moment)
    if not prev or not now:
        return {}
    out = {}
    for key, now_val in now.items():
        delta = int(now_val or 0) - int(prev.get(key) or 0)
        if delta > 0:
            out[key] = delta
    return out


@api_view(["GET"])
def views_anchors(request):
    """╨Ю╨┐╨╛╤А╨╜╤Л╨╡ ╤В╨╛╤З╨║╨╕ ╨┤╨╗╤П ┬л╨╢╨╕╨▓╤Л╤Е┬╗ ╤Б╤З╤С╤В╤З╨╕╨║╨╛╨▓ ╨╜╨░ ╤Д╤А╨╛╨╜╤В╨╡ тАФ ╨┐╨╛ ╨║╨░╨╢╨┤╨╛╨╝╤Г ╨┐╨╛╨║╨░╨╖╨░╤В╨╡╨╗╤О.

    ╨Ю╨║╨╜╨╛ ╤А╨╛╤Б╤В╨░: 10:00тАУ20:00 ╨┐╨╛ ╨Ь╨╛╤Б╨║╨▓╨╡. ╨д╤А╨╛╨╜╤В ╨▓╨╡╨┤╤С╤В ╤З╨╕╤Б╨╗╨╛ ╨╛╤В ``prev``
    (╨╖╨╜╨░╤З╨╡╨╜╨╕╨╡ ╨╜╨░ ╨┐╤А╨╛╤И╨╗╤Л╨╡ 10:00) ╨║ ``now`` (╨╜╨░ ╤Б╨╡╨│╨╛╨┤╨╜╤П╤И╨╜╨╕╨╡ 10:00) тАФ ╨╕╨╖╨╝╨╡╤А╨╡╨╜╨╜╤Л╨╣
    ╨┐╤А╨╕╤А╨╛╤Б╤В, ╤А╨░╤Б╤В╤П╨╜╤Г╤В╤Л╨╣ ╨┐╨╛ ╤Н╤В╨╕╨╝ 10 ╤З╨░╤Б╨░╨╝. ╨б 20:00 ╨┤╨╛ ╤Б╨╗╨╡╨┤╤Г╤О╤Й╨╕╤Е 10:00 ╤Ж╨╕╤Д╤А╨░
    ╤Б╤В╨╛╨╕╤В ╨╜╨░ ``now``. ╨Т╨╕╨┤╨╕╨╝╨╛╨╡ ╤З╨╕╤Б╨╗╨╛ ╨╛╤В╤Б╤В╨░╤С╤В ╨╛╤В ┬л╨╢╨╕╨▓╨╛╨╣┬╗ ╨▒╨░╨╖╤Л ╨┐╤А╨╕╨╝╨╡╤А╨╜╨╛ ╨╜╨░ ╤Б╤Г╤В╨║╨╕
    ╨╕ ╨╜╨╕╨║╨╛╨│╨┤╨░ ╨╡╤С ╨╜╨╡ ╨╛╨▒╨│╨╛╨╜╤П╨╡╤В.

    ``growth`` ╨╝╨╛╨╢╨╡╤В ╨▒╤Л╤В╤М ╨╜╤Г╨╗╤С╨╝ тАФ ╨╖╨╜╨░╤З╨╕╤В, ╨╖╨░ ╨┐╤А╨╛╤И╨╗╤Л╨╡ ╤Б╤Г╤В╨║╨╕ ╨┐╤А╨╛╨│╨╛╨╜╨╛╨▓ ╨╜╨╡ ╨▒╤Л╨╗╨╛ ╨╕
    ╨┐╨╛╨║╨░╨╖╨░╤В╨╡╨╗╤М ╨╜╨╡ ╨╝╨╡╨╜╤П╨╗╤Б╤П. ╨в╨╛╨│╨┤╨░ ╤Б╤З╤С╤В╤З╨╕╨║ ╤З╨╡╤Б╤В╨╜╨╛ ╤Б╤В╨╛╨╕╤В: ╨┤╨╛╤А╨╕╤Б╨╛╨▓╤Л╨▓╨░╤В╤М ╨┤╨▓╨╕╨╢╨╡╨╜╨╕╨╡,
    ╨║╨╛╤В╨╛╤А╨╛╨│╨╛ ╨╜╨╡ ╨▒╤Л╨╗╨╛, ╨╖╨╜╨░╤З╨╕╤В ╨┐╨╛╨║╨░╨╖╤Л╨▓╨░╤В╤М ╨▓╤Л╨┤╤Г╨╝╨░╨╜╨╜╤Л╨╡ ╤Ж╨╕╤Д╤А╤Л.

    ╨в╨╛╤З╨╜╨╛╤Б╤В╤М ╨╕╤Б╤В╨╛╤З╨╜╨╕╨║╨╛╨▓ ╤А╨░╨╖╨╜╨░╤П, ╨╕ ╤Н╤В╨╛ ╨▓╨╕╨┤╨╜╨╛ ╨▓ ``source`` ╨║╨░╨╢╨┤╨╛╨│╨╛ ╨┐╨╛╨║╨░╨╖╨░╤В╨╡╨╗╤П:

    - ``views`` ╨╕╨┤╤Г╤В ╨╕╨╖ ``AutoRefreshPoint``, ╨│╨┤╨╡ ╨╡╤Б╤В╤М ╨▓╤А╨╡╨╝╤П ╨╖╨░╨╝╨╡╤А╨░, ╨┐╨╛╤Н╤В╨╛╨╝╤Г
      ┬л╨╜╨░ 10:00┬╗ ╨╖╨┤╨╡╤Б╤М ╨▒╤Г╨║╨▓╨░╨╗╤М╨╜╨╛ ╨╜╨░ 10:00;
    - ╨╛╤Б╤В╨░╨╗╤М╨╜╤Л╨╡ тАФ ╨╕╨╖ ``AccountSnapshot``, ╨│╨┤╨╡ ╤Г ╤Б╨╜╨╕╨╝╨║╨░ ╤В╨╛╨╗╤М╨║╨╛ ╨┤╨░╤В╨░. ╨в╨░╨╝ ╨╛╨┐╨╛╤А╨░
      ╤Н╤В╨╛ ┬л╨║╨╛╨╜╨╡╤Ж ╨┤╨╜╤П┬╗, ╨░ ╨╜╨╡ 10:00. ╨а╤П╨┤╨░ ╤Б╨╛ ╨▓╤А╨╡╨╝╨╡╨╜╨╡╨╝ ╨┐╨╛ ╨╜╨╕╨╝ ╨▓ ╨▒╨░╨╖╨╡ ╨┐╤А╨╛╤Б╤В╨╛ ╨╜╨╡╤В.
    """
    now = timezone.localtime()
    window_start = now.replace(hour=VIEWS_ANCHOR_HOUR, minute=0, second=0, microsecond=0)
    if now < window_start:
        # ╨Ф╨╛ 10:00 ╨╡╤Й╤С ╨╕╨┤╤С╤В ╨▓╤З╨╡╤А╨░╤И╨╜╨╡╨╡ ╨╛╨║╨╜╨╛ (╤А╨╛╤Б╤В ╤Г╨╢╨╡ ╨╖╨░╨║╨╛╨╜╤З╨╡╨╜ ╨▓ 20:00 тАФ ╨╖╨░╨╝╨╛╤А╨╛╨╖╨║╨░).
        window_start -= datetime.timedelta(days=1)
    window_end = window_start.replace(
        hour=VIEWS_GROWTH_END_HOUR, minute=0, second=0, microsecond=0,
    )
    next_window_start = window_start + datetime.timedelta(days=1)
    # База эфира — понедельник прошлой недели в тот же час, не вчера.
    # Суточный зазор даёт десятки просмотров в секунду на 10-часовом окне.
    # Недельный зазор остаётся измеренным (точки и снимки), финиш — сегодняшние 10:00.
    # Списки аккаунтов, дельты и снимки этот сдвиг не меняет.
    this_monday = window_start.date() - datetime.timedelta(days=window_start.weekday())
    prev_monday = this_monday - datetime.timedelta(days=7)
    prev_start = window_start.replace(
        year=prev_monday.year, month=prev_monday.month, day=prev_monday.day,
    )

    def pair(now_val, prev_val, source):
        if now_val is None:
            now_val = prev_val
        if prev_val is None or now_val is None:
            growth = 0
        else:
            # ╨Ю╤В╤А╨╕╤Ж╨░╤В╨╡╨╗╤М╨╜╤Л╨╣ ╨┐╤А╨╕╤А╨╛╤Б╤В (╨░╨║╨║╨░╤Г╨╜╤В╤Л ╤Г╨┤╨░╨╗╨╕╨╗╨╕) ╨╜╨╡ ╨╛╤В╨╝╨░╤В╤Л╨▓╨░╨╡╨╝ ╨╜╨░╨╖╨░╨┤.
            growth = max(0, now_val - prev_val)
        return {"prev": prev_val, "now": now_val, "growth": growth, "source": source}

    scope = domains.resolve(request)
    metrics = {}
    at_now = at_prev = None

    # ╨Т╤Б╨╡ ╨┐╨╛╨║╨░╨╖╨░╤В╨╡╨╗╨╕ тАФ ╨┐╨╛ ╤Б╨╜╨╕╨╝╨║╨░╨╝, ╤Б ╤В╨╛╤З╨╜╨╛╤Б╤В╤М╤О ╨┤╨╛ ╨┤╨╜╤П.
    day_now = window_start.date()
    day_prev = prev_start.date()
    totals_now, n_now = _totals_as_of(day_now, scope)
    totals_prev, n_prev = _totals_as_of(day_prev, scope)
    for key in VC_METRICS:
        metrics[key] = pair(
            totals_now[key] if totals_now else None,
            totals_prev[key] if totals_prev else None,
            "account_snapshot",
        )

    # ╨С╨╡╨╖ ╨┤╨╛╨╝╨╡╨╜╨░ ╨┐╤А╨╛╤Б╨╝╨╛╤В╤А╨░╨╝ ╨╡╤Б╤В╤М ╨╕╤Б╤В╨╛╤З╨╜╨╕╨║ ╤В╨╛╤З╨╜╨╡╨╡: ╨▓ AutoRefreshPoint ╤Г ╨╖╨░╨╝╨╡╤А╨░
    # ╨╡╤Б╤В╤М ╨▓╤А╨╡╨╝╤П, ╨┐╨╛╤Н╤В╨╛╨╝╤Г ╨╛╨┐╨╛╤А╨░ ╨▒╤Г╨║╨▓╨░╨╗╤М╨╜╨╛ ╨╜╨░ 10:00, ╨░ ╨╜╨╡ ┬л╨╜╨░ ╨║╨╛╨╜╨╡╤Ж ╨┤╨╜╤П┬╗.
    # ╨Я╨╛ ╨┤╨╛╨╝╨╡╨╜╨░╨╝ ╨╛╨╜ ╨╜╨╡ ╤А╨░╨╖╨▒╨╕╤В, ╨┐╨╛╤Н╤В╨╛╨╝╤Г ╨▓╨╜╤Г╤В╤А╨╕ ╨┤╨╛╨╝╨╡╨╜╨░ ╨╛╤Б╤В╨░╤О╤В╤Б╤П ╤Б╨╜╨╕╨╝╨║╨╕.
    if not scope.unknown:
        views_now, at_now = _views_total_at(window_start, scope)
        views_prev, at_prev = _views_total_at(prev_start, scope)
        if views_prev is not None:
            metrics["views"] = pair(views_now, views_prev, "auto_refresh_point")

    return Response(
        {
            "tz": str(timezone.get_current_timezone()),
            "anchor_hour": VIEWS_ANCHOR_HOUR,
            "growth_end_hour": VIEWS_GROWTH_END_HOUR,
            # ╨з╤В╨╛╨▒╤Л ╤Д╤А╨╛╨╜╤В ╨┐╨╛╨┐╤А╨░╨▓╨╕╨╗ ╤Б╨▓╨╛╨╕ ╤З╨░╤Б╤Л: ╨┐╤А╨╕ ╤Б╨▒╨╕╤В╤Л╤Е ╨╗╨╛╨║╨░╨╗╤М╨╜╤Л╤Е ╤З╨░╤Б╨░╤Е ╨╛╨╜
            # ╨╕╨╜╨░╤З╨╡ ╨┐╨╛╨║╨░╨╢╨╡╤В ╤З╨╕╤Б╨╗╨╛ ╨╕╨╖ ╨┤╤А╤Г╨│╨╛╨│╨╛ ╨╝╨╡╤Б╤В╨░ ╤Б╤Г╤В╨╛╨║.
            "server_now": now.isoformat(),
            "window_start": window_start.isoformat(),
            "window_end": window_end.isoformat(),
            # ╨Э╨╛╨▓╤Л╨╡ ╤П╨║╨╛╤А╤П (╨╕ ╨╜╨╛╨▓╤Л╨╣ ╤А╨╛╤Б╤В) ╨╜╨░╤З╨╕╨╜╨░╤О╤В╤Б╤П ╨▓ ╤Б╨╗╨╡╨┤╤Г╤О╤Й╨╕╨╡ 10:00 тАФ ╨╜╨╡ ╨▓ 20:00.
            "next_window_start": next_window_start.isoformat(),
            "metrics": metrics,
            # Прирост просмотров по аккаунтам за окно. Фронт складывает по тем
            # аккаунтам, что сейчас на экране, и получает точный рост любого
            # среза — при любом сочетании фильтров рельса. Пусто, пока обе
            # опорные точки не обзаведутся разбивкой (примерно сутки после
            # выкладки); тогда фронт работает как раньше, разнося общий прирост.
            "account_growth": _account_growth_between(prev_start, window_start),
            "snapshot_days": {"now": str(day_now), "prev": str(day_prev),
                              "accounts_now": n_now, "accounts_prev": n_prev},
            # ╨б╤В╨░╤А╤Л╨╡ ╨║╨╗╤О╤З╨╕ ╨╛╤Б╤В╨░╨▓╨╗╨╡╨╜╤Л, ╤З╤В╨╛╨▒╤Л ╤Г╨╢╨╡ ╨▓╤Л╨╗╨╛╨╢╨╡╨╜╨╜╤Л╨╣ ╤Д╤А╨╛╨╜╤В ╨╜╨╡ ╤Б╨╗╨╛╨╝╨░╨╗╤Б╤П,
            # ╨┐╨╛╨║╨░ ╨▒╤Н╨║╨╡╨╜╨┤ ╨╕ ╤Д╤А╨╛╨╜╤В ╨▓╤Л╨║╨░╤В╤Л╨▓╨░╤О╤В╤Б╤П ╨┐╨╛ ╨╛╤В╨┤╨╡╨╗╤М╨╜╨╛╤Б╤В╨╕.
            "views_prev": metrics["views"]["prev"],
            "views_now": metrics["views"]["now"],
            "growth": metrics["views"]["growth"],
            "measured_prev_at": at_prev.isoformat() if at_prev else None,
            "measured_now_at": at_now.isoformat() if at_now else None,
        }
    )


@api_view(["GET"])
def auto_refresh_series(request):
    """
    ╨в╨╛╤З╨║╨╕ ╨░╨▓╤В╨╛╨╛╨▒╨╜╨╛╨▓╨╗╨╡╨╜╨╕╤П ╨┤╨╗╤П ╨│╤А╨░╤Д╨╕╨║╨░.

    - ╨б ╨┐╨░╤А╨░╨╝╨╡╤В╤А╨╛╨╝ ``date=YYYY-MM-DD`` тАФ ╨▓╤Б╨╡ ╤В╨╛╤З╨║╨╕ ╨╖╨░ ╨║╨░╨╗╨╡╨╜╨┤╨░╤А╨╜╤Л╨╣ ╨┤╨╡╨╜╤М (local_date).
    - ╨С╨╡╨╖ ``date`` тАФ ╤Б╨║╨╛╨╗╤М╨╖╤П╤Й╨╕╨╡ 24 ╤З╨░╤Б╨░ ╨┐╨╛ measured_at ╨┐╨╗╤О╤Б ╤Б╨╕╨╜╤В╨╡╤В╨╕╤З╨╡╤Б╨║╨░╤П ╤В╨╛╤З╨║╨░
      ╨▓ ╨╜╨░╤З╨░╨╗╨╡ ╨╛╨║╨╜╨░ (╨┐╨╛╤Б╨╗╨╡╨┤╨╜╨╕╨╣ ╨╕╨╖╨▓╨╡╤Б╤В╨╜╤Л╨╣ ╤Б╤Г╨╝╨╝╨░╤А╨╜╤Л╨╣ total), ╤З╤В╨╛╨▒╤Л ╨╗╨╕╨╜╨╕╤П ╨╜╨░ TV
      ╨╜╨╡ ┬л╨╛╨▒╤А╤Л╨▓╨░╨╗╨░╤Б╤М┬╗ ╨┤╨╛ ╨┐╨╡╤А╨▓╨╛╨│╨╛ ╨┐╤А╨╛╨│╨╛╨╜╨░ ╤В╨╡╨║╤Г╤Й╨╕╤Е ╤Б╤Г╤В╨╛╨║.
    """
    try:
        date_raw = (request.query_params.get("date") or "").strip()
        value_fields = (
            "id",
            "measured_at",
            "slot_label",
            "source",
            "view_count_total",
            "view_delta_from_prev_point",
            "view_delta_from_day_start",
            "platform_deltas",
        )
        if date_raw:
            try:
                target_date = datetime.date.fromisoformat(date_raw)
            except ValueError:
                return Response(
                    {"detail": "╨Э╨╡╨▓╨╡╤А╨╜╤Л╨╣ ╨┐╨░╤А╨░╨╝╨╡╤В╤А date. ╨Ш╤Б╨┐╨╛╨╗╤М╨╖╤Г╨╣╤В╨╡ ╤Д╨╛╤А╨╝╨░╤В YYYY-MM-DD."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            points_qs = AutoRefreshPoint.objects.filter(local_date=target_date).order_by("measured_at")
            points = list(points_qs.values(*value_fields))
            return Response({
                "date": str(target_date),
                "count": len(points),
                "points": points,
            })

        now = timezone.now()
        window_start = now - datetime.timedelta(hours=24)
        _chart_skip_sources = frozenset({"manual_seed_uneven"})

        def _rolling_anchor_baseline(prev_row, window_rows: list[dict]) -> int:
            if prev_row:
                return int(prev_row["view_count_total"])
            eligible = [
                int(p["view_count_total"])
                for p in window_rows
                if str(p.get("source") or "") not in _chart_skip_sources
            ]
            if eligible:
                return min(eligible)
            return int(window_rows[0]["view_count_total"])

        prev = (
            AutoRefreshPoint.objects.filter(measured_at__lt=window_start)
            .order_by("-measured_at")
            .values(*value_fields)
            .first()
        )
        in_window = list(
            AutoRefreshPoint.objects.filter(measured_at__gte=window_start, measured_at__lte=now)
            .order_by("measured_at")
            .values(*value_fields)
        )
        points: list[dict] = []
        if in_window:
            first_ts = in_window[0]["measured_at"]
            if first_ts > window_start:
                baseline = _rolling_anchor_baseline(prev, in_window)
                points.append({
                    "id": 0,
                    "measured_at": window_start,
                    "slot_label": "",
                    "source": "anchor",
                    "view_count_total": baseline,
                    "view_delta_from_prev_point": 0,
                    "view_delta_from_day_start": 0,
                    "platform_deltas": {},
                })
            points.extend(in_window)
        elif prev:
            baseline = int(prev["view_count_total"])
            points.append({
                "id": 0,
                "measured_at": window_start,
                "slot_label": "",
                "source": "anchor",
                "view_count_total": baseline,
                "view_delta_from_prev_point": 0,
                "view_delta_from_day_start": 0,
                "platform_deltas": {},
            })

        local_today = timezone.localtime(now).date()
        return Response({
            "date": str(local_today),
            "window": "rolling_24h",
            "count": len(points),
            "points": points,
        })
    except (ProgrammingError, OperationalError) as exc:
        return _schedule_db_error_response(exc)


@api_view(["GET"])
def auto_refresh_status(request):
    """
    ╨б╤В╨░╤В╤Г╤Б ╤Д╨╛╨╜╨╛╨▓╨╛╨│╨╛ ╨╛╨▒╨╜╨╛╨▓╨╗╨╡╨╜╨╕╤П (╨░╨▓╤В╨╛ + refresh_all). ╨б╨▒╤А╨░╤Б╤Л╨▓╨░╨╡╤В ╨╖╨░╨▓╨╕╤Б╤И╨╕╨╣ is_running ╨┐╨╛ ╤В╨░╨╣╨╝╨░╤Г╤В╤Г.
    """
    try:
        from .refresh_state import clear_stale_refresh_runs_if_needed

        clear_stale_refresh_runs_if_needed()
    except Exception:
        pass
    try:
        sched = RefreshScheduleConfig.get()
        try:
            sched.refresh_from_db(fields=["skip_recent_hours"])
        except Exception:
            pass
        skip_cfg = max(0, int(getattr(sched, "skip_recent_hours", 0) or 0))
        auto = AutoRefreshState.get()
        rr = RefreshAllState.get()

        def _coerce_rd(obj) -> dict:
            raw = getattr(obj, "run_detail", None) or {}
            return raw if isinstance(raw, dict) else {}

        from .auto_refresh_progress import progress_from_run_detail, refresh_run_in_progress

        auto_src = (getattr(auto, "source", None) or "").strip()
        auto_active = refresh_run_in_progress(auto, source=auto_src)
        rr_active = refresh_run_in_progress(rr, source="refresh_all")

        if auto_active:
            state = auto
            pipeline = "bulk_refresh" if auto_src == "bulk_refresh" else "scheduled_auto"
        elif rr_active:
            state = rr
            pipeline = "refresh_all"
        else:
            state = auto
            pipeline = None

        report_csv = (getattr(auto, "last_report_csv", None) or "").strip()
        rd = _coerce_rd(state) if pipeline else _coerce_rd(auto)
        done, total, progress = progress_from_run_detail(
            rd,
            db_total=int(state.total_accounts or 0),
            db_done=int(state.processed_accounts or 0),
        )
        resp_src = (getattr(state, "source", None) or "").strip()
        if pipeline == "refresh_all" and not resp_src:
            resp_src = "refresh_all"
        from .apps import peek_pending_scheduled_refresh_count

        pending = peek_pending_scheduled_refresh_count()
        return Response({
            "is_running": bool(auto_active or rr_active),
            "pending_scheduled_runs": pending,
            "active_pipeline": pipeline,
            "source": resp_src or (auto.source or "").strip(),
            "cancel_requested": bool(state.cancel_requested),
            "total_accounts": total,
            "processed_accounts": done,
            "success_accounts": max(0, int(state.success_accounts or 0)),
            "failed_accounts": max(0, int(state.failed_accounts or 0)),
            "progress_percent": progress,
            "current_account": state.current_account or None,
            "started_at": state.started_at,
            "finished_at": state.finished_at,
            "last_error": state.last_error or None,
            "updated_at": state.updated_at,
            "has_csv_report": bool(report_csv),
            "report_generated_at": auto.last_report_generated_at,
            "last_telegram_error": (getattr(auto, "last_telegram_error", None) or "").strip() or None,
            "last_telegram_sent_at": getattr(auto, "last_telegram_sent_at", None),
            "run_detail": rd,
            "skip_recent_hours_config": skip_cfg,
        })
    except (ProgrammingError, OperationalError) as exc:
        return _schedule_db_error_response(exc)


@api_view(["POST"])
def auto_refresh_run_now(request):
    """Start auto-refresh immediately in background."""
    try:
        from .refresh_state import clear_stale_refresh_runs_if_needed

        from .refresh_state import clear_orphan_cancel_flags

        clear_stale_refresh_runs_if_needed()
        clear_orphan_cancel_flags()
        state = AutoRefreshState.get()
        rr = RefreshAllState.get()
        if state.is_running or rr.is_running:
            return Response(
                {"started": False, "detail": "╨Р╨▓╤В╨╛╨╛╨▒╨╜╨╛╨▓╨╗╨╡╨╜╨╕╨╡ ╨╕╨╗╨╕ ╤Б╨▒╨╛╤А ╨▓╤Б╨╡╤Е ╤Г╨╢╨╡ ╨▓╤Л╨┐╨╛╨╗╨╜╤П╨╡╤В╤Б╤П."},
                status=status.HTTP_409_CONFLICT,
            )
        from .apps import _scheduled_refresh

        t = threading.Thread(
            target=_scheduled_refresh,
            kwargs={"source": "manual", "fast_start": True},
            daemon=True,
            name="auto-refresh-manual",
        )
        t.start()
        return Response({"started": True})
    except (ProgrammingError, OperationalError) as exc:
        return _schedule_db_error_response(exc)


@api_view(["POST"])
def auto_refresh_reset_state(request):
    """╨б╨▒╤А╨╛╤Б╨╕╤В╤М ╨╖╨░╨▓╨╕╤Б╤И╨╕╨╣ is_running (╨┐╨╛╤Б╨╗╨╡ warm_tiktok, ╤Б╨▒╨╛╤П ╨▓╨╛╤А╨║╨╡╤А╨╛╨▓). body/query: force=1."""
    try:
        from .refresh_state import clear_stale_refresh_runs_if_needed, clear_stuck_refresh_run

        raw = request.data.get("force") if hasattr(request, "data") else None
        if raw is None:
            raw = request.query_params.get("force")
        force = str(raw or "").strip().lower() in {"1", "true", "yes", "on"}
        if force:
            cleared = clear_stuck_refresh_run(
                reason="╨б╨▒╤А╨╛╤И╨╡╨╜╨╛ ╨▓╤А╤Г╤З╨╜╤Г╤О (API auto-refresh-reset-state).",
            )
        else:
            cleared = clear_stale_refresh_runs_if_needed()
        return Response({"cleared": cleared, "force": force})
    except (ProgrammingError, OperationalError) as exc:
        return _schedule_db_error_response(exc)


@api_view(["POST"])
def auto_refresh_stop(request):
    """Request graceful stop of currently running auto-refresh."""
    try:
        state = AutoRefreshState.get()
        if not state.is_running:
            return Response({"stopped": False, "detail": "╨Р╨▓╤В╨╛╨╛╨▒╨╜╨╛╨▓╨╗╨╡╨╜╨╕╨╡ ╤Б╨╡╨╣╤З╨░╤Б ╨╜╨╡ ╨▓╤Л╨┐╨╛╨╗╨╜╤П╨╡╤В╤Б╤П."}, status=status.HTTP_409_CONFLICT)
        from .refresh_state import force_stop_auto_refresh
        from platforms.apify.abort import abort_active_apify_jobs

        force_stop_auto_refresh(reason="╨Ю╤Б╤В╨░╨╜╨╛╨▓╨╗╨╡╨╜╨╛ ╨┐╨╛╨╗╤М╨╖╨╛╨▓╨░╤В╨╡╨╗╨╡╨╝.")
        abort_active_apify_jobs()
        state.refresh_from_db(fields=["is_running", "cancel_requested", "current_account", "updated_at"])
        return Response(
            {
                "stopped": True,
                "is_running": bool(state.is_running),
                "detail": (
                    "╨Ю╤Б╤В╨░╨╜╨╛╨▓╨║╨░ ╨┐╤А╨╕╨╜╤П╤В╨░. ╨б╤В╨░╤В╤Г╤Б ╤Б╨▒╤А╨╛╤И╨╡╨╜; ╨▒╤А╨░╤Г╨╖╨╡╤А╤Л ╨╖╨░╨║╤А╤Л╨▓╨░╤О╤В╤Б╤П ╨▓ ╤Д╨╛╨╜╨╡. "
                    "╨Ю╨▒╨╜╨╛╨▓╨╕╤В╨╡ ╤Б╤В╤А╨░╨╜╨╕╤Ж╤Г, ╨╡╤Б╨╗╨╕ ╨║╨╜╨╛╨┐╨║╨░ ╨╡╤Й╤С ┬л╨Ю╤Б╤В╨░╨╜╨╛╨▓╨║╨░тАж┬╗."
                ),
            },
        )
    except (ProgrammingError, OperationalError) as exc:
        return _schedule_db_error_response(exc)


@api_view(["GET"])
def auto_refresh_report_download(request):
    """╨б╨║╨░╤З╨░╤В╤М CSV ╨┐╨╛╤Б╨╗╨╡╨┤╨╜╨╡╨│╨╛ ╨╖╨░╨▓╨╡╤А╤И╤С╨╜╨╜╨╛╨│╨╛ ╨░╨▓╤В╨╛╨╛╨▒╨╜╨╛╨▓╨╗╨╡╨╜╨╕╤П (╨╡╤Б╨╗╨╕ ╨▓╨║╨╗╤О╤З╨╡╨╜╨╛ ╨▓ ╨╜╨░╤Б╤В╤А╨╛╨╣╨║╨░╤Е)."""
    try:
        state = AutoRefreshState.get()
        body = (getattr(state, "last_report_csv", None) or "").strip()
        if not body:
            return Response(
                {"detail": "╨Ю╤В╤З╤С╤В ╨╡╤Й╤С ╨╜╨╡ ╤Б╤Д╨╛╤А╨╝╨╕╤А╨╛╨▓╨░╨╜. ╨Ф╨╛╨╢╨┤╨╕╤В╨╡╤Б╤М ╨╖╨░╨▓╨╡╤А╤И╨╡╨╜╨╕╤П ╨░╨▓╤В╨╛╨╛╨▒╨╜╨╛╨▓╨╗╨╡╨╜╨╕╤П ╤Б ╨▓╨║╨╗╤О╤З╤С╨╜╨╜╤Л╨╝ CSV."},
                status=status.HTTP_404_NOT_FOUND,
            )
        ts = state.last_report_generated_at or timezone.now()
        fname = f"auto-refresh-report-{timezone.localtime(ts).strftime('%Y%m%d-%H%M%S')}.csv"
        resp = HttpResponse(
            body.encode("utf-8-sig"),
            content_type="text/csv; charset=utf-8",
        )
        resp["Content-Disposition"] = f'attachment; filename="{fname}"'
        return resp
    except (ProgrammingError, OperationalError) as exc:
        return _schedule_db_error_response(exc)


@api_view(["GET"])
def auto_refresh_last_error_ids(request):
    """ID ╨░╨║╨║╨░╤Г╨╜╤В╨╛╨▓ ╤Б╨╛ ╤Б╤В╨░╤В╤Г╤Б╨╛╨╝ ┬л╨╛╤И╨╕╨▒╨║╨░┬╗ ╨▓ ╨┐╨╛╤Б╨╗╨╡╨┤╨╜╨╡╨╝ ╨╖╨░╨▓╨╡╤А╤И╤С╨╜╨╜╨╛╨╝ ╨░╨▓╤В╨╛╨╛╨▒╨╜╨╛╨▓╨╗╨╡╨╜╨╕╨╕ ╨┐╨╛ ╤А╨░╤Б╨┐╨╕╤Б╨░╨╜╨╕╤О."""
    try:
        from .auto_refresh_csv import extract_error_account_ids_from_saved_auto_refresh_csv

        state = AutoRefreshState.get()
        raw = getattr(state, "last_auto_refresh_error_account_ids", None) or []
        ids: list[int] = []
        if isinstance(raw, list):
            for x in raw:
                try:
                    ids.append(int(x))
                except (TypeError, ValueError):
                    continue
        ids = sorted(set(ids))
        if not ids:
            csv_body = (getattr(state, "last_report_csv", None) or "").strip()
            if csv_body:
                ids = extract_error_account_ids_from_saved_auto_refresh_csv(csv_body)
        return Response({"ids": ids, "count": len(ids)})
    except (ProgrammingError, OperationalError) as exc:
        return _schedule_db_error_response(exc)


@api_view(["GET"])
def refresh_all_status(request):
    """╨б╤В╨░╤В╤Г╤Б ╤Д╨╛╨╜╨╛╨▓╨╛╨│╨╛ POST /api/accounts/refresh_all/ (╨╛╤З╨╡╤А╨╡╨┤╤М, ╤Б╨╗╨╛╤В╤Л ╨▓╨╛╤А╨║╨╡╤А╨╛╨▓)."""
    try:
        st = RefreshAllState.get()
        total = max(0, int(st.total_accounts or 0))
        done = max(0, int(st.processed_accounts or 0))
        progress = 0 if total <= 0 else min(100, int(round((done / total) * 100)))
        report_csv = (getattr(st, "last_report_csv", None) or "").strip()
        rd = getattr(st, "run_detail", None) or {}
        if not isinstance(rd, dict):
            rd = {}
        completion_summary = rd.get("completion_summary")
        if not isinstance(completion_summary, dict):
            completion_summary = None
        report_run = rd.get("report_run")
        if not isinstance(report_run, dict):
            report_run = None
        return Response({
            "is_running": bool(st.is_running),
            "cancel_requested": bool(st.cancel_requested),
            "total_accounts": total,
            "processed_accounts": done,
            "success_accounts": max(0, int(st.success_accounts or 0)),
            "failed_accounts": max(0, int(st.failed_accounts or 0)),
            "progress_percent": progress,
            "current_account": st.current_account or None,
            "started_at": st.started_at,
            "finished_at": st.finished_at,
            "last_error": st.last_error or None,
            "completion_summary": completion_summary,
            "report_run": report_run,
            "updated_at": st.updated_at,
            "has_csv_report": bool(report_csv),
            "report_generated_at": st.last_report_generated_at,
            "run_detail": rd,
        })
    except (ProgrammingError, OperationalError) as exc:
        return _schedule_db_error_response(exc)


@api_view(["POST"])
def refresh_all_stop(request):
    """╨Ч╨░╨┐╤А╨╛╤Б╨╕╤В╤М ╨╛╤Б╤В╨░╨╜╨╛╨▓╨║╤Г ╤В╨╡╨║╤Г╤Й╨╡╨│╨╛ ╤Б╨▒╨╛╤А╨░ ╨▓╤Б╨╡╤Е ╨░╨║╨║╨░╤Г╨╜╤В╨╛╨▓."""
    try:
        st = RefreshAllState.get()
        if not st.is_running:
            return Response(
                {"stopped": False, "detail": "╨б╨▒╨╛╤А ╨▓╤Б╨╡╤Е ╨░╨║╨║╨░╤Г╨╜╤В╨╛╨▓ ╤Б╨╡╨╣╤З╨░╤Б ╨╜╨╡ ╨▓╤Л╨┐╨╛╨╗╨╜╤П╨╡╤В╤Б╤П."},
                status=status.HTTP_409_CONFLICT,
            )
        st.cancel_requested = True
        st.save(update_fields=["cancel_requested", "updated_at"])
        from .refresh_interrupt import interrupt_refresh_playwright_workers
        from platforms.apify.abort import abort_active_apify_jobs

        interrupt_refresh_playwright_workers(label="refresh_all_stop")
        abort_active_apify_jobs()
        return Response({"stopped": True})
    except (ProgrammingError, OperationalError) as exc:
        return _schedule_db_error_response(exc)


@api_view(["GET"])
def refresh_all_report_download(request):
    """╨б╨║╨░╤З╨░╤В╤М CSV ╨╛╤В╤З╤С╤В╨░ ╨┐╨╛╤Б╨╗╨╡╨┤╨╜╨╡╨│╨╛ ╨╖╨░╨▓╨╡╤А╤И╤С╨╜╨╜╨╛╨│╨╛ ╤Б╨▒╨╛╤А╨░ ╨▓╤Б╨╡╤Е (GET /api/accounts/refresh-all-report/)."""
    try:
        st = RefreshAllState.get()
        body = (getattr(st, "last_report_csv", None) or "").strip()
        if not body:
            return Response(
                {
                    "detail": (
                        "╨Ю╤В╤З╤С╤В ╨╡╤Й╤С ╨╜╨╡ ╤Б╤Д╨╛╤А╨╝╨╕╤А╨╛╨▓╨░╨╜. ╨Ч╨░╨┐╤Г╤Б╤В╨╕╤В╨╡ ╤Б╨▒╨╛╤А ╨▓╤Б╨╡╤Е ╨░╨║╨║╨░╤Г╨╜╤В╨╛╨▓ "
                        "╨╕ ╨┤╨╛╨╢╨┤╨╕╤В╨╡╤Б╤М ╨╖╨░╨▓╨╡╤А╤И╨╡╨╜╨╕╤П тАФ CSV ╤Б╨╛╤Е╤А╨░╨╜╨╕╤В╤Б╤П ╨╜╨░ ╤Б╨╡╤А╨▓╨╡╤А╨╡ ╨░╨▓╤В╨╛╨╝╨░╤В╨╕╤З╨╡╤Б╨║╨╕."
                    ),
                },
                status=status.HTTP_404_NOT_FOUND,
            )
        ts = st.last_report_generated_at or timezone.now()
        fname = f"refresh-all-report-{timezone.localtime(ts).strftime('%Y%m%d-%H%M%S')}.csv"
        resp = HttpResponse(
            body.encode("utf-8-sig"),
            content_type="text/csv; charset=utf-8",
        )
        resp["Content-Disposition"] = f'attachment; filename="{fname}"'
        return resp
    except (ProgrammingError, OperationalError) as exc:
        return _schedule_db_error_response(exc)


def account_avatar(request, pk: int):
    """
    ╨Р╨▓╨░╤В╨░╤А: ╨╗╨╛╨║╨░╨╗╤М╨╜╤Л╨╣ ╤Д╨░╨╣╨╗, ╨╕╨╜╨░╤З╨╡ ╨┐╤А╨╛╨║╤Б╨╕ avatar_url (CDN).
    GET /api/accounts/<pk>/avatar/
    """
    from .avatar_storage import serve_account_avatar_response

    return serve_account_avatar_response(pk)


def post_thumbnail(request, pk: int):
    """
    ╨Я╤А╨╡╨▓╤М╤О ╨┐╨╛╤Б╤В╨░: ╨╗╨╛╨║╨░╨╗╤М╨╜╤Л╨╣ ╤Д╨░╨╣╨╗, ╨╕╨╜╨░╤З╨╡ ╨┐╤А╨╛╨║╤Б╨╕ thumbnail_url (CDN).
    GET /api/posts/<pk>/thumbnail/
    """
    from .post_thumbnail_storage import serve_post_thumbnail_response

    return serve_post_thumbnail_response(pk)


# ---------------------------------------------------------------------------
# Темы домена AI (многие-ко-многим с аккаунтами)
# ---------------------------------------------------------------------------

def _topic_row(t):
    return {
        "id": t.id, "name": t.name, "slug": t.slug, "color": t.color,
        "emoji": t.emoji, "sort_order": t.sort_order,
        "account_ids": sorted(a.id for a in t.accounts.all()),
    }


_TOPIC_TRANSLIT = dict(zip(
    "абвгдеёжзийклмнопрстуфхцчшщъыьэюя",
    ["a", "b", "v", "g", "d", "e", "e", "zh", "z", "i", "y", "k", "l", "m", "n", "o", "p", "r", "s",
     "t", "u", "f", "h", "ts", "ch", "sh", "sch", "", "y", "", "e", "yu", "ya"],
))
_TOPIC_COLOR_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")


def _topic_slug(name, exclude_pk=None):
    from django.utils.text import slugify
    from .models import Topic
    base = slugify("".join(_TOPIC_TRANSLIT.get(ch, ch) for ch in name.lower()))[:50] or "topic"
    slug, n = base, 2
    while Topic.objects.filter(slug=slug).exclude(pk=exclude_pk).exists():
        slug, n = f"{base}-{n}", n + 1
    return slug


def _topic_apply(topic, data):
    """Проверяем и применяем name / emoji / color / sort_order. Вернёт текст ошибки или None."""
    if "name" in data:
        name = str(data.get("name") or "").strip()
        if not name:
            return "Название темы не может быть пустым"
        if len(name) > 120:
            return "Название длиннее 120 символов"
        topic.name = name
    if "emoji" in data:
        emoji = str(data.get("emoji") or "").strip()
        if len(emoji) > 8:
            return "Смайлик — один символ"
        topic.emoji = emoji
    if "color" in data:
        color = str(data.get("color") or "").strip()
        if not _TOPIC_COLOR_RE.match(color):
            return "Цвет в формате #RRGGBB"
        topic.color = color
    if "sort_order" in data:
        try:
            topic.sort_order = int(data.get("sort_order"))
        except (TypeError, ValueError):
            return "sort_order — число"
    return None


def _topic_board(request):
    """Чьи темы: домен из запроса (ai или stands), без домена — ai."""
    scope = domains.resolve(request)
    return scope.domain.slug if domains.is_topics(scope) else "ai"


@api_view(["GET", "POST"])
def topic_list(request):
    """GET — темы AI и id их аккаунтов. POST — новая тема {name, emoji?, color?}."""
    from django.db.models import Max
    from .models import Topic
    board = _topic_board(request)
    mine = Topic.objects.filter(board=board)
    if request.method == "POST":
        topic = Topic(color="#6366f1", board=board)
        err = _topic_apply(topic, {"name": request.data.get("name", ""), **{
            k: request.data[k] for k in ("emoji", "color") if k in request.data}})
        if err:
            return Response({"detail": err}, status=status.HTTP_400_BAD_REQUEST)
        if mine.filter(name__iexact=topic.name).exists():
            return Response({"detail": f"«{topic.name}» уже есть"}, status=status.HTTP_400_BAD_REQUEST)
        topic.slug = _topic_slug(topic.name)
        topic.sort_order = (mine.aggregate(m=Max("sort_order"))["m"] or 0) + 10
        topic.save()
        return Response(_topic_row(topic), status=status.HTTP_201_CREATED)
    return Response([_topic_row(t) for t in mine.prefetch_related("accounts")])


@api_view(["PATCH", "DELETE"])
def topic_detail(request, pk):
    """PATCH — переименовать / сменить смайлик или цвет. DELETE — удалить тему.

    Удаление темы не трогает аккаунты: исчезает только их связь с этой темой.
    """
    from .models import Topic
    topic = get_object_or_404(Topic, pk=pk)
    if request.method == "DELETE":
        topic.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
    err = _topic_apply(topic, request.data)
    if err:
        return Response({"detail": err}, status=status.HTTP_400_BAD_REQUEST)
    if Topic.objects.filter(board=topic.board, name__iexact=topic.name).exclude(pk=topic.pk).exists():
        return Response({"detail": f"«{topic.name}» уже есть"}, status=status.HTTP_400_BAD_REQUEST)
    topic.save()
    topic = Topic.objects.prefetch_related("accounts").get(pk=topic.pk)
    return Response(_topic_row(topic))


@api_view(["POST"])
def topic_accounts(request, pk):
    """Добавить / убрать аккаунты темы: {"account_ids": [...], "action": "add"|"remove"}.

    Меняется только состав темы. Домен, группа и другие темы аккаунта не
    трогаются — поэтому аккаунт ниоткуда не «переезжает».
    """
    from .models import Topic
    topic = get_object_or_404(Topic, pk=pk)
    raw = request.data.get("account_ids") or []
    if not isinstance(raw, list):
        return Response({"detail": "account_ids должен быть списком"}, status=status.HTTP_400_BAD_REQUEST)
    try:
        ids = sorted({int(x) for x in raw})
    except (TypeError, ValueError):
        return Response({"detail": "account_ids: только числа"}, status=status.HTTP_400_BAD_REQUEST)
    act = str(request.data.get("action") or "add").lower()
    found = list(Account.objects.filter(id__in=ids).values_list("id", flat=True))
    if act == "remove":
        topic.accounts.remove(*found)
    elif act == "add":
        topic.accounts.add(*found)
    else:
        return Response({"detail": "action: add или remove"}, status=status.HTTP_400_BAD_REQUEST)
    topic = Topic.objects.prefetch_related("accounts").get(pk=topic.pk)
    return Response(_topic_row(topic))


@api_view(["GET", "PUT"])
def topic_board_order(request):
    """Порядок карточек на экране AI. GET → {"account_ids": [...]}; PUT с тем же телом сохраняет.

    Список общий для всех пользователей: последний сохранённый побеждает.
    """
    from .models import TopicBoard
    board, _ = TopicBoard.objects.get_or_create(key=_topic_board(request))
    if request.method == "PUT":
        raw = request.data.get("account_ids")
        if not isinstance(raw, list):
            return Response({"detail": "account_ids должен быть списком"}, status=status.HTTP_400_BAD_REQUEST)
        if len(raw) > 20000:
            return Response({"detail": "Слишком длинный список"}, status=status.HTTP_400_BAD_REQUEST)
        seen, ids = set(), []
        try:
            for x in raw:
                i = int(x)
                if i not in seen:
                    seen.add(i)
                    ids.append(i)
        except (TypeError, ValueError):
            return Response({"detail": "account_ids: только числа"}, status=status.HTTP_400_BAD_REQUEST)
        board.account_ids = ids
        board.save(update_fields=["account_ids", "updated_at"])
    return Response({"account_ids": board.account_ids or []})


@api_view(["POST"])
def topic_new_accounts(request, pk):
    """Завести аккаунты с нуля и сразу поставить на стенд.

    Тело: {"items": [{"username", "platform"}...], "profile_id", "owner_id",
    "group_id", "country_id"}. Новый аккаунт получает домен ветки. Уже
    существующий просто встаёт на стенд: домен и метки не трогаем, иначе он
    исчез бы из своей ветки. Аккаунт, стоящий на другом стенде этой ветки,
    остаётся там — в ветке он живёт в одном месте.
    """
    from .models import Topic
    topic = get_object_or_404(Topic, pk=pk)
    items = request.data.get("items")
    if not isinstance(items, list) or not items:
        return Response({"detail": "Нет аккаунтов"}, status=status.HTTP_400_BAD_REQUEST)
    if len(items) > 500:
        return Response({"detail": "Не больше 500 за раз"}, status=status.HTTP_400_BAD_REQUEST)
    domain = Domain.objects.filter(slug=topic.board).first()
    labels = {k: request.data.get(k) for k in ("profile_id", "owner_id", "group_id", "country_id")}
    elsewhere = dict(
        Topic.accounts.through.objects.filter(topic__board=topic.board).exclude(topic=topic)
        .values_list("account_id", "topic__name")
    )
    out = {"created": 0, "placed": 0, "already": 0, "elsewhere": [], "errors": [], "account_ids": []}
    for item in items:
        item = item if isinstance(item, dict) else {}
        name = str(item.get("username") or "")
        ser = AccountSerializer(data={
            "username": name, "platform": item.get("platform"), **labels,
            **({"domain_id": domain.id} if domain else {}),
        })
        if not ser.is_valid():
            first = next(iter(ser.errors.values()))
            out["errors"].append(f"{name}: {first[0] if isinstance(first, list) else first}")
            continue
        v = ser.validated_data
        same = Account.objects.filter(platform=v["platform"])
        # Регистр в ссылке и в базе часто разный (youtube.com/@gretahalbig
        # против сохранённого GretaHalbig) — без iexact заводился дубль.
        account = (same.filter(username=v["username"]).first()
                   or same.filter(username__iexact=v["username"]).first())
        if account is None:
            account = ser.save()
            _stamp_new_account_updated_at(account.pk)
            topic.accounts.add(account)
            out["created"] += 1
        else:
            _unarchive_account_on_import(account)
            _unban_account_on_import(account)
            if account.id in elsewhere:
                out["elsewhere"].append(f"{account.username} — {elsewhere[account.id]}")
                continue
            if topic.accounts.filter(pk=account.pk).exists():
                out["already"] += 1
            else:
                topic.accounts.add(account)
                out["placed"] += 1
        out["account_ids"].append(account.id)
    return Response(out)


@api_view(["POST"])
def topic_remove_accounts(request):
    """Убрать аккаунты со всех тем ветки по списку ссылок/имён.

    Тело: {"items": [{"username", "platform"}...]}. Ветка — из X-Domain.
    Аккаунт снимается со всех её тем (стендов). Если он и заведён был здесь
    (домен = эта ветка), то уходит в архив: иначе так и висел бы в домене,
    невидимый на экране, и продолжал бы собираться. Аккаунты других веток
    только снимаются со стендов. Ничего не удаляется насовсем.
    """
    from .models import Topic, TopicBoard
    board = _topic_board(request)
    items = request.data.get("items")
    if not isinstance(items, list) or not items:
        return Response({"detail": "Нет аккаунтов"}, status=status.HTTP_400_BAD_REQUEST)
    if len(items) > 500:
        return Response({"detail": "Не больше 500 за раз"}, status=status.HTTP_400_BAD_REQUEST)
    through = Topic.accounts.through
    out = {"removed": 0, "archived": 0, "not_found": [], "not_here": []}
    gone = set()
    for item in items:
        item = item if isinstance(item, dict) else {}
        name = str(item.get("username") or "").strip().lstrip("@")
        platform = str(item.get("platform") or "").strip().lower()
        if not name:
            continue
        cands = Account.objects.filter(platform=platform) if platform else Account.objects.all()
        account = (cands.filter(username__iexact=name).first()
                   or cands.filter(username__iexact="@" + name).first())
        if account is None:
            out["not_found"].append(name)
            continue
        links = through.objects.filter(topic__board=board, account_id=account.id)
        if not links.exists():
            out["not_here"].append(name)
            continue
        links.delete()
        gone.add(account.id)
        out["removed"] += 1
        if account.domain_id and account.domain.slug == board and not account.is_archived:
            account.is_archived = True
            account.save(update_fields=["is_archived"])
            out["archived"] += 1
    if gone:
        tb = TopicBoard.objects.filter(key=board).first()
        if tb and tb.account_ids:
            tb.account_ids = [i for i in tb.account_ids if i not in gone]
            tb.save(update_fields=["account_ids", "updated_at"])
    return Response(out)
