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
)
from django.db import transaction
from django.db.utils import OperationalError, ProgrammingError
from rest_framework import viewsets, status
from rest_framework.decorators import api_view, action
from rest_framework.parsers import JSONParser, MultiPartParser
from rest_framework.response import Response
from .models import (
    Account, Platform, Post, Profile, AccountSnapshot, PostSnapshot, AutoRefreshPoint, AutoRefreshState,
    GlobalVisibilityConfig,
)
from .serializers import AccountSerializer, PostSerializer, ProfileSerializer
from .snapshot_io import build_snapshot_csv, import_snapshot_csv
from platforms.profile_unavailable import (
    is_profile_unavailable_error,
    user_visible_profile_unavailable_error,
)

logger = logging.getLogger(__name__)


def _mark_profile_unavailable_if_applicable(account: Account, exc: BaseException) -> None:
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


def _scrape(account: Account) -> dict:
    """Fetch fresh data for any platform. Returns account fields + '_posts' list."""
    username = account.username
    platform = account.platform

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
            # Пробрасываем флаг авторитетности списка постов из service.py.
            # Для TikTok пустой `videos` почти всегда — антибот/временная блокировка
            # API, а не реальное удаление всех постов профиля. В этом случае
            # service.py выставляет _posts_authoritative=False, и _apply_refresh
            # сохраняет уже сохранённые в БД посты вместо их удаления.
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

    raise ValueError(f"Обновление для «{platform}» не поддерживается.")


def _sync_posts(account: Account, posts_data: list) -> None:
    today = timezone.localdate()
    seen_external_ids: set[str] = set()
    is_instagram = account.platform == Platform.INSTAGRAM
    is_threads = account.platform == Platform.THREADS

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
        # Update content fields
        for field in ("description", "thumbnail_url", "post_url", "posted_at"):
            if field in pd and pd[field] is not None:
                setattr(post, field, pd[field])
        # Update numeric fields with resilient coercion + fallback aliases
        parsed_views = _to_int(pd.get("view_count", pd.get("play_count", 0)))
        # Threads / Instagram: 0 со скрапа часто «нет в DOM / не успели», а не реальные 0 просмотров.
        # Не затираем сохранённые значения — иначе сумма по постам и дельты в UI падают в минус.
        if is_threads or is_instagram:
            if parsed_views > 0:
                prev_v = int(post.view_count or 0)
                post.view_count = max(prev_v, parsed_views)
            # parsed_views == 0 — не трогаем post.view_count
        else:
            post.view_count = parsed_views
        parsed_like_count = _to_int(pd.get("like_count", pd.get("digg_count", 0)))
        # Instagram: 0 со скрапа = «данных нет», не уменьшаем сохранённые лайки.
        # Положительное значение считаем валидным и применяем только не ниже уже сохранённого.
        if is_instagram:
            if parsed_like_count > 0:
                prev_likes = int(post.like_count or 0)
                post.like_count = max(prev_likes, parsed_like_count)
        else:
            post.like_count = parsed_like_count
        post.comment_count = _to_int(pd.get("comment_count", 0))
        post.share_count = _to_int(pd.get("share_count", 0))
        # Extract and store hashtags from description
        post.hashtags = _extract_hashtags(post.description)
        post.save()
        # Keep today's post snapshot current — correct baseline for tomorrow's delta.
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

    # Full sync: remove posts that disappeared from platform (deleted/hidden).
    # Их исторические снэпшоты остаются в БД, но из текущих списков и агрегатов
    # они уходят.
    #
    # ВНИМАНИЕ: удалять «всё» при пустом `posts_data` опасно — на скриншоте у
    # пользователя один сбой парсинга TikTok стирал все ранее сохранённые
    # посты профиля. Авторитетный пустой список (например, действительно
    # пустой профиль) обрабатывается выше через `_posts_authoritative=False`
    # → ветка `_sync_posts` вообще не вызывается, либо явно вызывается с
    # `posts_data=[]` только когда у нас есть гарантия, что пост-list
    # действительно пуст.
    if posts_data:
        account.posts.exclude(external_id__in=seen_external_ids).delete()
    elif account.post_count == 0:
        # Профиль действительно пуст по счётчику — можно подчистить.
        account.posts.all().delete()


_STAT_FIELDS = frozenset(
    ("follower_count", "like_count", "view_count", "post_count")
)


def _refresh_stats_trustworthy(account: Account, stats_before: dict[str, int]) -> bool:
    """Успешное обновление для UI «обновлён»: не недоступный профиль и не «обнуление» при ненулевой базе."""
    if bool(getattr(account, "profile_unavailable", False)):
        return False
    # У Facebook view_count намеренно обнуляется в пайплайне — не считаем это сбоем.
    fields = ["follower_count", "like_count", "post_count"]
    if account.platform != Platform.FACEBOOK:
        fields.insert(2, "view_count")
    for f in fields:
        prev = int(stats_before.get(f, 0) or 0)
        cur = int(getattr(account, f, 0) or 0)
        if prev > 0 and cur == 0:
            return False
    return True

# Парсеры (особенно Instagram og:image при антиботе) иногда отдают пустую строку —
# не затираем уже сохранённый CDN-URL, иначе в UI пропадает аватарка до следующего удачного парса.
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
    """
    platform_defaults: dict[str, tuple[float, float]] = {
        Platform.INSTAGRAM: (0.0, 0.0),
        Platform.TIKTOK: (0.8, 1.6),
        Platform.X: (0.8, 1.6),
        Platform.THREADS: (0.8, 1.6),
        Platform.FACEBOOK: (0.8, 1.6),
        Platform.YOUTUBE: (0.3, 0.8),
        Platform.TELEGRAM: (0.3, 0.8),
        Platform.RUMBLE: (0.5, 1.0),
        Platform.REDDIT: (0.4, 0.9),
    }
    dmin, dmax = platform_defaults.get(account.platform, (0.6, 1.2))
    key = account.platform.upper()
    lo = _get_float_setting(f"REFRESH_ALL_DELAY_{key}_MIN", dmin)
    hi = _get_float_setting(f"REFRESH_ALL_DELAY_{key}_MAX", dmax)
    # Backward-compatible global clamp/fallback
    global_lo = _get_float_setting("REFRESH_ALL_DELAY_MIN", lo)
    global_hi = _get_float_setting("REFRESH_ALL_DELAY_MAX", hi)
    a = max(0.0, min(lo, hi, global_lo, global_hi))
    b = max(lo, hi, global_lo, global_hi)
    if b <= 0:
        return 0.0
    if a == b:
        return a
    return random.uniform(a, b)


def _format_refresh_error(account: Account, exc: BaseException) -> tuple[str, int]:
    _mark_profile_unavailable_if_applicable(account, exc)
    if isinstance(exc, ValueError):
        return user_visible_profile_unavailable_error(str(exc)), status.HTTP_400_BAD_REQUEST
    return f"Ошибка: {exc}", status.HTTP_502_BAD_GATEWAY


def _refresh_account_for_api(account: Account, *, scraped: dict | None = None) -> tuple[Account | None, str | None, int | None]:
    try:
        return _refresh_with_retry(account, scraped=scraped), None, None
    except Exception as exc:
        detail, code = _format_refresh_error(account, exc)
        return None, detail, code


def _prewarm_workers(accounts: list[Account]) -> None:
    """
    Start daemon workers upfront for platforms present in refresh_all batch.
    This opens one browser window per used platform at the beginning.
    """
    from platforms.worker_pool import ensure_worker

    used_platforms = {acc.platform for acc in accounts}
    for platform in used_platforms:
        worker = _PLATFORM_WORKERS.get(platform)
        if not worker:
            continue
        if worker.exists():
            try:
                ensure_worker(worker)
            except Exception as e:
                logger.warning("refresh.prewarm_failed", extra={"platform": platform, "error": str(e)})


def _apply_refresh(account: Account, scraped: dict | None = None) -> Account:
    snap, _ = account.take_snapshot_if_needed()
    logger.info(
        "refresh.snapshot_before",
        extra={
            "account_id": account.id,
            "platform": account.platform,
            "username": account.username,
            "snapshot_date": str(snap.date),
        },
    )
    # Копия, чтобы .pop() не портил кэш preload при нескольких IG подряд.
    data = dict(scraped) if scraped is not None else _scrape(account)
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
    # when follower counts were unavailable) — preserve existing DB stats.
    is_partial = data.pop("_partial", False)
    posts_authoritative = data.pop("_posts_authoritative", True)
    has_posts_key = "_posts" in data
    posts = data.pop("_posts", [])
    for field, value in data.items():
        if not hasattr(account, field):
            # Some scrapers return extra fields (e.g. following_count) that are
            # not stored in Account model; skip them without breaking refresh.
            continue
        if is_partial and field in _STAT_FIELDS:
            continue  # don't zero-out existing stats on a partial update
        if value is not None:
            if field in _SKIP_EMPTY_STR_UPDATE and isinstance(value, str) and not value.strip():
                continue
            setattr(account, field, value)

    with transaction.atomic():
        if has_posts_key and (posts_authoritative or posts):
            try:
                _sync_posts(account, posts)
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
            except Exception as e:
                logger.exception(
                    "refresh.posts_sync_failed",
                    extra={"account_id": account.id, "platform": account.platform, "username": account.username},
                )
        elif has_posts_key and not posts_authoritative:
            print(
                f"[posts] keeping existing posts for @{account.username}: "
                "empty non-authoritative list from scraper",
            )

        # Aggregate view_count from posts for most platforms.
        # For YouTube and Telegram the like_count is also post-derived
        # (the platform page doesn't expose a channel-level like counter).
        agg = account.posts.aggregate(
            total_views=Sum("view_count"),
            total_likes=Sum("like_count"),
        )
        # Facebook view_count is partial/misleading as a profile-level metric
        # (scraper visibility is inconsistent), keep it 0.
        # Instagram now supports view aggregation from reels/posts.
        if account.platform == Platform.FACEBOOK:
            account.view_count = 0
        # Rumble exposes account-level cumulative views on /about; keep scraper value.
        elif account.platform == Platform.RUMBLE:
            pass
        else:
            account.view_count = agg["total_views"] or 0
        # For platforms that don't expose a channel-level like counter,
        # aggregate from post likes instead.
        if account.platform in (
            Platform.YOUTUBE, Platform.TELEGRAM, Platform.INSTAGRAM,
            Platform.X, Platform.THREADS, Platform.RUMBLE, Platform.REDDIT,
        ):
            account.like_count = agg["total_likes"] or 0
        # If the scraper didn't return a post_count (returned 0/None), fall back to
        # the number of posts we actually have stored — better than showing a dash.
        stored_post_count = account.posts.count()
        if not account.post_count and stored_post_count:
            account.post_count = stored_post_count

        if not _refresh_stats_trustworthy(account, stats_before):
            raise ValueError(
                "Данные выглядят как ошибка или недоступность: нулевые метрики при ненулевых в базе "
                "или профиль помечен недоступным. Обновление не применено."
            )

        account.updated_at = timezone.now()
        account.save()

        # Keep today's snapshot up-to-date with the freshly-scraped/aggregated values.
        # This is the baseline used by tomorrow's delta calculation.
        snap.follower_count = account.follower_count
        snap.like_count = account.like_count
        snap.view_count = account.view_count
        snap.post_count = account.post_count
        snap.save(update_fields=[
            "follower_count", "like_count", "view_count", "post_count",
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
        )

        # Fix snapshots where view_count is still 0 — these are snapshots created
        # before the view_count field was added to AccountSnapshot (migration 0006).
        # Without this, delta = current_view_count - 0 = full count (wrong).
        account.snapshots.filter(
            date__lt=snap.date,
            view_count=0,
        ).update(view_count=account.view_count)

        # Fix snapshots where post_count is still 0 — happens when a scraper only
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
        ):
            account.snapshots.filter(
                date__lt=snap.date,
                like_count=0,
            ).update(like_count=account.like_count)

    return account


def _refresh_with_retry(account: Account, scraped: dict | None = None) -> Account:
    """
    Avoid aggressive retry loops on flaky platforms:
    - profile-not-found style errors fail fast;
    - transient errors are retried a limited number of times.
    """
    max_attempts = int(getattr(settings, "REFRESH_RETRY_ATTEMPTS", 2) or 2)
    max_attempts = max(1, min(max_attempts, 3))
    last_exc: Exception | None = None
    for attempt in range(max_attempts):
        try:
            return _apply_refresh(account, scraped=scraped)
        except ValueError:
            raise
        except Exception as exc:
            last_exc = exc
            msg = str(exc).lower()
            if "не найден" in msg or "not found" in msg:
                raise
            if attempt >= max_attempts - 1:
                raise
            time.sleep(0.8 + attempt * 0.6)
    assert last_exc is not None
    raise last_exc


class AccountViewSet(viewsets.ModelViewSet):
    serializer_class = AccountSerializer

    def get_queryset(self):
        # Для detail-операций аккаунт должен быть доступен по ID даже если он
        # скрыт глобальными фильтрами (иначе delete/retrieve дают 404).
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
        prev_snapshots = AccountSnapshot.objects.filter(
            account=OuterRef("pk"),
            date__lt=today,
        ).order_by("-date")

        qs = Account.objects.select_related("profile").annotate(
            _prev_follower_count=Subquery(prev_snapshots.values("follower_count")[:1]),
            _prev_like_count=Subquery(prev_snapshots.values("like_count")[:1]),
            _prev_view_count=Subquery(prev_snapshots.values("view_count")[:1]),
            _prev_post_count=Subquery(prev_snapshots.values("post_count")[:1]),
        ).annotate(
            _follower_delta=F("follower_count") - F("_prev_follower_count"),
            _like_delta=F("like_count") - F("_prev_like_count"),
            _view_delta=F("view_count") - F("_prev_view_count"),
            _post_delta=F("post_count") - F("_prev_post_count"),
        )
        platform = self.request.query_params.get("platform")
        if platform:
            qs = qs.filter(platform=platform)
        profile_id = self.request.query_params.get("profile_id")
        if profile_id == "none":
            qs = qs.filter(profile__isnull=True)
        elif profile_id:
            qs = qs.filter(profile_id=profile_id)
        search = self.request.query_params.get("search", "").strip()
        if search:
            qs = qs.filter(
                Q(username__icontains=search) | Q(display_name__icontains=search)
            )
        return _apply_visibility_filters(
            qs,
            include_hidden_platforms=include_hidden_platforms,
            include_hidden_profiles=include_hidden_profiles,
        )

    def get_serializer_context(self):
        ctx = super().get_serializer_context()
        ctx["hidden_platforms"] = _get_hidden_platforms()
        return ctx

    @action(detail=True, methods=["post"])
    def refresh(self, request, pk=None):
        account = self.get_object()
        with _account_refresh_mutex(account.id):
            refreshed, detail, code = _refresh_account_for_api(account)
            if refreshed is not None:
                return Response(AccountSerializer(refreshed).data)
            return Response({"detail": detail}, status=code)

    @action(detail=False, methods=["post"], url_path="bulk-refresh")
    def bulk_refresh(self, request):
        """
        Обновить несколько аккаунтов за один запрос.
        Для нескольких Instagram с Instaloader: один Playwright-сеанс на все /reels/.
        """
        ids = request.data.get("ids")
        if not isinstance(ids, list) or not ids:
            return Response(
                {"detail": "Передайте массив ids"},
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
                {"detail": "В ids должны быть числовые идентификаторы аккаунтов"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        by_id = {a.id: a for a in Account.objects.filter(id__in=id_ints).select_related("profile")}
        ordered: list[Account] = []
        for i in id_ints:
            if i in by_id:
                ordered.append(by_id[i])
        if not ordered:
            return Response({"detail": "Аккаунты не найдены"}, status=status.HTTP_404_NOT_FOUND)

        state = AutoRefreshState.get()
        if state.is_running:
            return Response(
                {"detail": "Сейчас уже выполняется другое автообновление/обновление."},
                status=status.HTTP_409_CONFLICT,
            )
        state.is_running = True
        state.source = "bulk_refresh"
        state.cancel_requested = False
        state.total_accounts = len(ordered)
        state.processed_accounts = 0
        state.success_accounts = 0
        state.failed_accounts = 0
        state.current_account = ""
        state.last_error = ""
        state.started_at = timezone.now()
        state.finished_at = None
        state.run_detail = {}
        state.save(update_fields=[
            "is_running", "source", "cancel_requested", "total_accounts",
            "processed_accounts", "success_accounts", "failed_accounts",
            "current_account", "last_error", "started_at", "finished_at",
            "run_detail", "updated_at",
        ])

        try:
            _prewarm_workers(ordered)

            ig_accounts = [a for a in ordered if a.platform == Platform.INSTAGRAM]
            preload: dict[str, dict] = {}
            if len(ig_accounts) > 1:
                try:
                    from platforms.instagram.scraper import fetch_instagram_profiles_bulk

                    preload = fetch_instagram_profiles_bulk([a.username for a in ig_accounts])
                except Exception as e:
                    print(f"[bulk_refresh] instagram bulk prefetch failed: {e}", file=sys.stderr)
                    preload = {}

            accounts_out: list[dict] = []
            errors_out: list[dict] = []
            stop_requested = threading.Event()
            state_lock = threading.Lock()

            for a in ordered:
                if stop_requested.is_set():
                    break
                with state_lock:
                    state.refresh_from_db(fields=["cancel_requested"])
                    if state.cancel_requested:
                        stop_requested.set()
                        state.last_error = "Обновление остановлено пользователем."
                        state.save(update_fields=["last_error", "updated_at"])
                        break
                    state.current_account = f"{a.platform}/@{a.username}"
                    state.save(update_fields=["current_account", "updated_at"])

                with _account_refresh_mutex(a.id):
                    key = _normalize_instagram_username_key(a.username)
                    scraped = None
                    if (
                        a.platform == Platform.INSTAGRAM
                        and len(ig_accounts) > 1
                        and key in preload
                    ):
                        scraped = preload[key]
                    account, detail, _ = _refresh_account_for_api(a, scraped=scraped)

                with state_lock:
                    state.processed_accounts += 1
                    if account is not None:
                        state.success_accounts += 1
                    else:
                        state.failed_accounts += 1
                        state.last_error = str(detail or "")
                    state.save(update_fields=[
                        "processed_accounts", "success_accounts", "failed_accounts",
                        "last_error", "updated_at",
                    ])

                if account is not None:
                    accounts_out.append(AccountSerializer(account).data)
                else:
                    errors_out.append({"id": a.id, "detail": detail})

            return Response({
                "accounts": accounts_out,
                "errors": errors_out,
                "cancelled": bool(stop_requested.is_set()),
            })
        finally:
            finished = timezone.now()
            state.refresh_from_db()
            state.is_running = False
            state.cancel_requested = False
            state.current_account = ""
            state.finished_at = finished
            state.run_detail = {}
            state.save(update_fields=[
                "is_running", "cancel_requested", "current_account",
                "finished_at", "run_detail", "updated_at",
            ])

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
                {"detail": "Передайте файл в поле file"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            summary = import_snapshot_csv(upload)
        except Exception as e:
            return Response(
                {"detail": f"Ошибка разбора CSV: {e}"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(summary)

    @action(detail=False, methods=["post"])
    def refresh_all(self, request):
        refreshed, failed, errors = 0, 0, []
        report_rows = []
        include_hidden = _coerce_bool(request.query_params.get("include_hidden"))
        include_hidden_platforms = include_hidden or _coerce_bool(
            request.query_params.get("include_hidden_platforms"),
        )
        include_hidden_profiles = include_hidden or _coerce_bool(
            request.query_params.get("include_hidden_profiles"),
        )
        accounts_qs = Account.objects.all().order_by("platform", "id")
        accounts_qs = _apply_visibility_filters(
            accounts_qs,
            include_hidden_platforms=include_hidden_platforms,
            include_hidden_profiles=include_hidden_profiles,
        )
        accounts = list(accounts_qs)

        def _int_env(name: str, default: int, *, min_v: int = 1, max_v: int = 32) -> int:
            raw = os.environ.get(name)
            if raw is None:
                return default
            try:
                val = int(str(raw).strip())
            except Exception:
                return default
            return max(min_v, min(max_v, val))

        def _platform_limits() -> dict[str, int]:
            defaults: dict[str, int] = {
                Platform.TIKTOK: 1,
                Platform.INSTAGRAM: 1,
                Platform.THREADS: 1,
                Platform.FACEBOOK: 1,
                Platform.RUMBLE: 1,
                Platform.TELEGRAM: 2,
                Platform.X: 2,
                Platform.REDDIT: 2,
                Platform.YOUTUBE: 2,
            }
            limits: dict[str, int] = {}
            for p in {a.platform for a in accounts}:
                env_key = f"AUTO_REFRESH_CONCURRENCY_{str(p).upper()}"
                limits[p] = _int_env(env_key, defaults.get(p, 1), min_v=1, max_v=8)
            return limits

        def _interleave_accounts_by_platform(items: list[Account]) -> list[Account]:
            buckets: dict[str, list[Account]] = {}
            platform_order: list[str] = []
            for acc in items:
                p = str(acc.platform)
                if p not in buckets:
                    buckets[p] = []
                    platform_order.append(p)
                buckets[p].append(acc)
            out: list[Account] = []
            while True:
                pushed = False
                for p in platform_order:
                    arr = buckets.get(p) or []
                    if arr:
                        out.append(arr.pop(0))
                        pushed = True
                if not pushed:
                    break
            return out

        accounts = _interleave_accounts_by_platform(accounts)
        _prewarm_workers(accounts)

        ig_all = [a for a in accounts if a.platform == Platform.INSTAGRAM]
        ig_preload: dict[str, dict] = {}
        if len(ig_all) > 1:
            try:
                from platforms.instagram.scraper import fetch_instagram_profiles_bulk

                ig_preload = fetch_instagram_profiles_bulk([a.username for a in ig_all])
            except Exception as e:
                print(f"[refresh_all] instagram bulk prefetch failed: {e}", file=sys.stderr)
                ig_preload = {}

        queue_lock = threading.Lock()
        report_lock = threading.Lock()
        counter_lock = threading.Lock()
        cooldown_lock = threading.Lock()
        next_idx = 0
        report_by_index: list[dict | None] = [None] * len(accounts)
        platform_limits = _platform_limits()
        platform_semaphores = {
            p: threading.BoundedSemaphore(value=max(1, int(v)))
            for p, v in platform_limits.items()
        }
        platform_next_allowed_at = {p: 0.0 for p in platform_limits.keys()}
        worker_count = _int_env("AUTO_REFRESH_WORKERS", 4, min_v=1, max_v=16)

        def _claim_index() -> int | None:
            nonlocal next_idx
            with queue_lock:
                if next_idx >= len(accounts):
                    return None
                idx = next_idx
                next_idx += 1
                return idx

        def _worker() -> None:
            nonlocal refreshed, failed
            while True:
                idx = _claim_index()
                if idx is None:
                    return
                account = accounts[idx]
                before = {
                    "follower_count": account.follower_count,
                    "like_count": account.like_count,
                    "view_count": account.view_count,
                    "post_count": account.post_count,
                }

                sem = platform_semaphores.get(account.platform)
                if sem is None:
                    sem = threading.BoundedSemaphore(value=1)
                    platform_semaphores[account.platform] = sem
                    with cooldown_lock:
                        platform_next_allowed_at.setdefault(account.platform, 0.0)

                with sem:
                    while True:
                        with cooldown_lock:
                            wait_sec = platform_next_allowed_at.get(account.platform, 0.0) - time.monotonic()
                        if wait_sec <= 0:
                            break
                        time.sleep(min(0.2, wait_sec))

                    try:
                        ig_key = _normalize_instagram_username_key(account.username)
                        with _account_refresh_mutex(account.id):
                            if (
                                account.platform == Platform.INSTAGRAM
                                and len(ig_all) > 1
                                and ig_key in ig_preload
                            ):
                                _refresh_with_retry(account, scraped=ig_preload[ig_key])
                            else:
                                _refresh_with_retry(account)
                        account.refresh_from_db(fields=["follower_count", "like_count", "view_count", "post_count"])
                        after = {
                            "follower_count": account.follower_count,
                            "like_count": account.like_count,
                            "view_count": account.view_count,
                            "post_count": account.post_count,
                        }
                        changed = {k: (after[k] != before[k]) for k in before}
                        changed_count = sum(1 for v in changed.values() if v)
                        if changed_count == 0:
                            status_label = "нет обновлений"
                        else:
                            status_label = "обновилось"
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
                        with counter_lock:
                            refreshed += 1
                    except Exception as e:
                        detail, _ = _format_refresh_error(account, e)
                        row = {
                            "id": account.id,
                            "platform": account.platform,
                            "username": account.username,
                            "status": "ошибка",
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
                        with counter_lock:
                            failed += 1
                            errors.append(f"@{account.username} ({account.platform}): {detail}")
                    finally:
                        pause_sec = _refresh_all_delay_seconds(account)
                        if pause_sec > 0:
                            with cooldown_lock:
                                platform_next_allowed_at[account.platform] = max(
                                    platform_next_allowed_at.get(account.platform, 0.0),
                                    time.monotonic() + pause_sec,
                                )

                with report_lock:
                    report_by_index[idx] = row

        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            futures = [executor.submit(_worker) for _ in range(worker_count)]
            for f in futures:
                f.result()

        report_rows = [r for r in report_by_index if r is not None]

        if request.query_params.get("download_csv") in {"1", "true", "yes"}:
            buffer = io.StringIO()
            writer = csv.writer(buffer)
            writer.writerow([
                "platform",
                "username",
                "status",
                "follower_count",
                "follower_delta",
                "like_count",
                "like_delta",
                "view_count",
                "view_delta",
                "post_count",
                "post_delta",
                "error",
            ])
            for row in report_rows:
                writer.writerow([
                    row.get("platform", ""),
                    row.get("username", ""),
                    row.get("status", ""),
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
            payload = buffer.getvalue()
            response = HttpResponse("\ufeff" + payload, content_type="text/csv; charset=utf-8")
            response["Content-Disposition"] = 'attachment; filename="refresh_all_report.csv"'
            return response

        return Response({
            "refreshed": refreshed,
            "failed": failed,
            "errors": errors,
            "report": report_rows,
        })

    @action(detail=True, methods=["get"])
    def posts(self, request, pk=None):
        account = self.get_object()
        today = timezone.localdate()
        prev_post_snapshots = PostSnapshot.objects.filter(
            post=OuterRef("pk"),
            date__lt=today,
        ).order_by("-date")
        qs = account.posts.annotate(
            _prev_view_count=Subquery(prev_post_snapshots.values("view_count")[:1]),
            _prev_like_count=Subquery(prev_post_snapshots.values("like_count")[:1]),
            _prev_comment_count=Subquery(prev_post_snapshots.values("comment_count")[:1]),
        ).annotate(
            _view_delta=F("view_count") - F("_prev_view_count"),
            _like_delta=F("like_count") - F("_prev_like_count"),
            _comment_delta=F("comment_count") - F("_prev_comment_count"),
        )
        return Response(PostSerializer(qs, many=True).data)


class ProfileViewSet(viewsets.ModelViewSet):
    serializer_class = ProfileSerializer

    def get_queryset(self):
        qs = Profile.objects.annotate(account_count=Count("accounts"))
        include_hidden_profiles = _coerce_bool(self.request.query_params.get("include_hidden_profiles"))
        action = getattr(self, "action", "") or ""
        # По списку скрытые не показываем без флага; по ID — всегда находим запись,
        # иначе PATCH/DELETE скрытого профиля дают 404.
        detail_actions = {"retrieve", "update", "partial_update", "destroy"}
        if action in detail_actions:
            return qs
        if not include_hidden_profiles:
            qs = qs.filter(is_hidden=False)
        return qs

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
    """Сумма дневных дельт за календарный «вчера»: snap(вчера) − snap(позавчера) по каждому аккаунту.

    `today` — календарный день в активной таймзоне (см. summary: timezone.localdate()), для продакшена Europe/Moscow.
    Нужна для масштаба мини-графиков на TV: вчерашний прирост = 50% высоты при равенстве с сегодняшним.
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
    """Сумма (последний снимок − предыдущий) по каждому аккаунту, оба с date < today.

    Используется, когда нет пары снимков ровно за календарный «вчера» и «позавчера», но история уже есть
    (например, дневной снимок за «вчера» ещё не создан до ночного цикла). Интервал между двумя датами
    может быть больше суток — это всё равно осмысленная опорная дельта для масштаба графика, не выдумка.
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


@api_view(["GET"])
def summary(request):
    """Aggregate stats + deltas across all accounts, grouped by platform."""
    today = timezone.localdate()
    include_hidden = _coerce_bool(request.query_params.get("include_hidden"))
    include_hidden_platforms = include_hidden or _coerce_bool(request.query_params.get("include_hidden_platforms"))
    include_hidden_profiles = include_hidden or _coerce_bool(request.query_params.get("include_hidden_profiles"))
    qs = Account.objects.prefetch_related("snapshots").all()
    qs = _apply_visibility_filters(
        qs,
        include_hidden_platforms=include_hidden_platforms,
        include_hidden_profiles=include_hidden_profiles,
    )
    accounts = list(qs)

    total = {"follower_count": 0, "like_count": 0, "view_count": 0, "post_count": 0}
    snap_total = {"follower_count": 0, "like_count": 0, "view_count": 0, "post_count": 0}
    has_snaps = False
    by_platform: dict[str, dict] = {}

    for acc in accounts:
        for key in total:
            total[key] += getattr(acc, key)

        snap = acc.snapshots.filter(date__lt=today).order_by("-date").first()
        if snap:
            has_snaps = True
            snap_total["follower_count"] += snap.follower_count
            snap_total["like_count"] += snap.like_count
            snap_total["view_count"] += snap.view_count
            snap_total["post_count"] += snap.post_count

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
            }
        by_platform[p]["account_count"] += 1
        for key in ("follower_count", "like_count", "view_count", "post_count"):
            by_platform[p][key] += getattr(acc, key)

    account_ids = [int(a.pk) for a in accounts]
    y_follow, y_like, y_view, y_post = _aggregate_yesterday_calendar_deltas(account_ids, today)
    if y_follow is None:
        y_follow, y_like, y_view, y_post = _aggregate_prev_snapshot_pair_deltas(account_ids, today)

    return Response({
        "account_count": len(accounts),
        "follower_count": total["follower_count"],
        "like_count": total["like_count"],
        "view_count": total["view_count"],
        "post_count": total["post_count"],
        "follower_delta": total["follower_count"] - snap_total["follower_count"] if has_snaps else None,
        "like_delta": total["like_count"] - snap_total["like_count"] if has_snaps else None,
        "view_delta": total["view_count"] - snap_total["view_count"] if has_snaps else None,
        "post_delta": total["post_count"] - snap_total["post_count"] if has_snaps else None,
        "yesterday_follower_delta": y_follow,
        "yesterday_like_delta": y_like,
        "yesterday_view_delta": y_view,
        "yesterday_post_delta": y_post,
        "by_platform": list(by_platform.values()),
    })


def _schedule_db_error_response(exc: BaseException) -> Response:
    logger.warning("schedule/auto-refresh DB error: %s", exc)
    return Response(
        {
            "detail": (
                "Ошибка базы данных (автообновление / расписание). "
                "На сервере выполните «python manage.py migrate» в каталоге backend и перезапустите процесс."
            ),
        },
        status=status.HTTP_503_SERVICE_UNAVAILABLE,
    )


def _schedule_to_dict(config) -> dict:
    return {
        "enabled": config.enabled,
        "mode": config.mode,
        "interval_hours": config.interval_hours,
        "skip_recent_hours": config.skip_recent_hours,
        "auto_refresh_csv_report": bool(
            getattr(config, "auto_refresh_csv_report", False),
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
        "times": config.times,
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
    from .models import RefreshScheduleConfig
    from .apps import get_scheduler, apply_schedule_config

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
        if "auto_refresh_csv_report" in data:
            config.auto_refresh_csv_report = _coerce_bool(data["auto_refresh_csv_report"])
        if "include_hidden_platform_accounts" in data:
            config.include_hidden_platform_accounts = _coerce_bool(data["include_hidden_platform_accounts"])
        if "include_hidden_profile_accounts" in data:
            config.include_hidden_profile_accounts = _coerce_bool(data["include_hidden_profile_accounts"])
        if "include_unavailable_accounts" in data:
            config.include_unavailable_accounts = _coerce_bool(data["include_unavailable_accounts"])
        if "times" in data and isinstance(data["times"], list):
            valid = []
            for t in data["times"]:
                try:
                    h, m = map(int, str(t).split(":"))
                    assert 0 <= h <= 23 and 0 <= m <= 59
                    valid.append(f"{h:02d}:{m:02d}")
                except Exception:
                    pass
            config.times = valid
        config.save()

        sched = get_scheduler()
        if sched:
            apply_schedule_config(config, sched)

        return Response(_schedule_to_dict(config))
    except (ProgrammingError, OperationalError) as exc:
        return _schedule_db_error_response(exc)


@api_view(["GET"])
def auto_refresh_series(request):
    """
    Точки автообновления для графика.

    - С параметром ``date=YYYY-MM-DD`` — все точки за календарный день (local_date).
    - Без ``date`` — скользящие 24 часа по measured_at плюс синтетическая точка
      в начале окна (последний известный суммарный total), чтобы линия на TV
      не «обрывалась» до первого прогона текущих суток.
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
                    {"detail": "Неверный параметр date. Используйте формат YYYY-MM-DD."},
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
                baseline = int(prev["view_count_total"]) if prev else int(in_window[0]["view_count_total"])
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
    """Current/last auto-refresh run status for UI progress widget."""
    try:
        from .models import RefreshScheduleConfig

        sched = RefreshScheduleConfig.get()
        try:
            sched.refresh_from_db(fields=["skip_recent_hours"])
        except Exception:
            pass
        skip_cfg = max(0, int(getattr(sched, "skip_recent_hours", 0) or 0))
        state = AutoRefreshState.get()
        total = max(0, int(state.total_accounts or 0))
        done = max(0, int(state.processed_accounts or 0))
        progress = 0 if total <= 0 else min(100, int(round((done / total) * 100)))
        report_csv = (getattr(state, "last_report_csv", None) or "").strip()
        rd = getattr(state, "run_detail", None) or {}
        if not isinstance(rd, dict):
            rd = {}
        return Response({
            "is_running": bool(state.is_running),
            "source": state.source,
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
            "report_generated_at": state.last_report_generated_at,
            "run_detail": rd,
            "skip_recent_hours_config": skip_cfg,
        })
    except (ProgrammingError, OperationalError) as exc:
        return _schedule_db_error_response(exc)


@api_view(["POST"])
def auto_refresh_run_now(request):
    """Start auto-refresh immediately in background."""
    try:
        state = AutoRefreshState.get()
        if state.is_running:
            return Response(
                {"started": False, "detail": "Автообновление уже выполняется."},
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
def auto_refresh_stop(request):
    """Request graceful stop of currently running auto-refresh."""
    try:
        state = AutoRefreshState.get()
        if not state.is_running:
            return Response({"stopped": False, "detail": "Автообновление сейчас не выполняется."}, status=status.HTTP_409_CONFLICT)
        state.cancel_requested = True
        state.save(update_fields=["cancel_requested", "updated_at"])
        return Response({"stopped": True})
    except (ProgrammingError, OperationalError) as exc:
        return _schedule_db_error_response(exc)


@api_view(["GET"])
def auto_refresh_report_download(request):
    """Скачать CSV последнего завершённого автообновления (если включено в настройках)."""
    try:
        state = AutoRefreshState.get()
        body = (getattr(state, "last_report_csv", None) or "").strip()
        if not body:
            return Response(
                {"detail": "Отчёт ещё не сформирован. Дождитесь завершения автообновления с включённым CSV."},
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


def account_avatar(request, pk: int):
    """
    Proxy an account's avatar from its CDN URL.
    Avoids CDN expiry and hotlink issues on the frontend.
    GET /api/accounts/<pk>/avatar/
    """
    try:
        account = Account.objects.get(pk=pk)
    except Account.DoesNotExist:
        return HttpResponse(status=404)

    url = account.avatar_url
    if not url and account.platform == Platform.TIKTOK:
        # Не подставляем thumbnail поста как аватар: это приводит к ложной "аватарке"
        # из видео. Для TikTok держим только профильные источники.
        try:
            from platforms.tiktok.service import _extract_avatar_from_html

            profile_url = f"https://www.tiktok.com/@{account.username}"
            r_prof = httpx.get(
                profile_url,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/124.0.0.0 Safari/537.36"
                    ),
                    "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
                    "Accept": (
                        "text/html,application/xhtml+xml,application/xml;q=0.9,"
                        "*/*;q=0.8"
                    ),
                },
                follow_redirects=True,
                timeout=15.0,
            )
            if r_prof.status_code == 200 and r_prof.text:
                url = _extract_avatar_from_html(r_prof.text)
        except Exception:
            pass
    if not url and account.platform == Platform.THREADS:
        # Meta CDN для аватара иногда пустой в DOM; превью первого поста обычно доступно.
        first_post = account.posts.exclude(thumbnail_url="").order_by("-id").first()
        if first_post:
            url = first_post.thumbnail_url
    if not url:
        return HttpResponse(status=404)

    referer_by_platform = {
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

    try:
        r = httpx.get(
            url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
                "Referer": referer_by_platform.get(account.platform, "https://www.google.com/"),
                "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
            },
            follow_redirects=True,
            timeout=10.0,
        )
    except Exception:
        return HttpResponse(status=502)

    if r.status_code != 200:
        return HttpResponse(status=404)

    content_type = r.headers.get("content-type", "image/jpeg").split(";")[0]
    response = HttpResponse(r.content, content_type=content_type)
    # Cache for 2 hours in the browser; CDN tokens typically last days
    response["Cache-Control"] = "max-age=7200, public"
    response["X-Content-Type-Options"] = "nosniff"
    return response
