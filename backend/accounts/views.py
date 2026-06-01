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
from .constants import MAX_AUDIENCE_FOLLOWERS_PER_TRACKED_ACCOUNT
from .audience import AUDIENCE_SYNC_SUPPORTED_PLATFORMS
from .models import (
    Account,
    AccountAudienceMembership,
    Platform,
    Post,
    Profile,
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
    AudienceMemberDetailSerializer,
    AudienceMemberListSerializer,
    PostSerializer,
    ProfileSerializer,
)
from .snapshot_io import build_snapshot_csv, import_snapshot_csv, _is_deadlock_error
from platforms.profile_unavailable import (
    is_profile_unavailable_error,
    user_visible_profile_unavailable_error,
)

logger = logging.getLogger(__name__)


def _is_refresh_stats_rejection(exc: BaseException) -> bool:
    """Отказ сохранить подозрительные нули — не путать с удалённым профилем на площадке."""
    return "Обновление не применено" in str(exc or "")


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
    """Дельты аккаунтов: опорный снимок — последний с датой ≤ сегодня − N дней (1, 7 или 30)."""
    try:
        cfg = RefreshScheduleConfig.get()
        d = int(getattr(cfg, "account_delta_period_days", 1) or 1)
    except Exception:
        return 1
    return d if d in (1, 7, 30) else 1


def _effective_account_delta_period_days(request) -> int:
    """
    Для GET: можно передать delta_period_days=1|7|30 — не пишет в БД, удобно для префетча UI.
    Для остальных методов и при отсутствии/невалидном параметре — значение из RefreshScheduleConfig.
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

    # Не держим соединение с БД открытым во время Playwright/HTTP (минуты).
    release_db_for_long_task()
    raise_if_refresh_cancel_requested()
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


def _mark_unseen_posts_missing(account: Account, seen_external_ids: set[str]) -> None:
    """Пометить посты, отсутствующие в успешном съёме (оранжевая лампочка в UI)."""
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
        # Facebook: 0 без подтверждения — «данных нет»; confirmed после detail (кнопка в viewport) — пишем 0.
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

    if seen_external_ids:
        # Пост снова в съёме — снимаем «не найден» (лампочка в UI пропадает).
        account.posts.filter(external_id__in=seen_external_ids).update(
            missing_from_scrape_at=None,
        )
    if mark_unseen_missing:
        _mark_unseen_posts_missing(account, seen_external_ids)
    return seen_external_ids


def _posts_for_account_stats(account: Account):
    """Посты, участвующие в суммах просмотров/лайков и в счётчике публикаций."""
    return account.posts.filter(missing_from_scrape_at__isnull=True)


def _apply_post_aggregates_to_account(account: Account, stats_before: dict) -> None:
    """
    Пересчёт view_count / like_count / post_count по постам без «не найден при скрапе».
    Итоговые значения не уменьшаем относительно stats_before (помеченные посты не «роняют» метрики).
    """
    agg = _posts_for_account_stats(account).aggregate(
        total_views=Sum("view_count"),
        total_likes=Sum("like_count"),
    )
    new_views = int(agg["total_views"] or 0)
    prev_views = int(stats_before.get("view_count", 0) or 0)
    if account.platform == Platform.FACEBOOK:
        account.view_count = max(prev_views, new_views)
    elif account.platform == Platform.RUMBLE:
        account.view_count = max(prev_views, int(account.view_count or 0))
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
    account.post_count = max(prev_post_count, active_post_count, scraped_post_count)


_STAT_FIELDS = frozenset(
    ("follower_count", "like_count", "view_count", "post_count")
)

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


def _restore_account_updated_at(account_id: int, preserved) -> None:
    """После неуспешного refresh не трогаем «Обновлён» в UI (auto_now / частичный save)."""
    if preserved is None:
        return
    Account.objects.filter(pk=account_id).update(updated_at=preserved)


def _account_refresh_baseline(account: Account) -> dict:
    from .refresh_cancel import account_refresh_baseline

    return account_refresh_baseline(account)


def _restore_account_refresh_baseline(account_id: int, baseline: dict | None) -> None:
    from .refresh_cancel import restore_account_refresh_baseline

    restore_account_refresh_baseline(account_id, baseline)


def _refresh_stats_trustworthy(account: Account, stats_before: dict[str, int]) -> bool:
    """Успешное обновление для UI «обновлён»: не недоступный профиль и не «обнуление» при ненулевой базе."""
    if bool(getattr(account, "profile_unavailable", False)):
        return False
    fields = ["follower_count", "like_count", "view_count", "post_count"]
    # Threads: метрики уровня профиля и агрегаты по постам нестабильны (DOM, meta, пустые лайки).
    # Ложное «обнуление» по follower/like/post ломало сохранение и залипал profile_unavailable.
    # Оставляем только защиту по view_count (для Threads он ещё и max с предыдущим в пайплайне).
    if account.platform == Platform.THREADS:
        fields = ["view_count"]
    elif account.platform == Platform.INSTAGRAM:
        # Подписчики и лайки со скрапа часто 0 при лимитах/антиботе при том же живом профиле;
        # полная проверка как у «обычных» платформ давала ложный отказ и HTTP 400 без сохранения.
        # Защищаемся от подозрительного обнуления по просмотрам и числу постов.
        fields = ["view_count", "post_count"]
    elif account.platform == Platform.TIKTOK:
        # TikTok: в UI профиль живой (ролики на месте), а follower/like с парсера часто 0
        # (антибот, гость, урезанный SSR) — иначе refresh откатывается, хотя посты обновились.
        fields = ["view_count", "post_count"]
    elif account.platform == Platform.FACEBOOK:
        # Сумма лайков по постам может закономерно обнулиться (все посты ≤ MIN_VIEWS для детальных лайков).
        # Подписчики со скрапа часто 0 при той же живой странице (DOM / headless / язык блока) —
        # если требовать «не обнулять follower_count», весь refresh откатывается и **не сохраняются**
        # лайки постов после enrich. Не включаем follower_count и like_count в эту проверку.
        fields = ["view_count", "post_count"]
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
    Facebook: 2–5 мин между аккаунтами (120–300 с) — Playwright + антибот.
    TikTok: пауза между аккаунтами 30–90 с (снижает капчу на профилях; env REFRESH_ALL_DELAY_TIKTOK_*).
    YouTube: пауза 5–10 с между аккаунтами — снижает риск квот/блокировок при серии запросов.
    """
    platform_defaults: dict[str, tuple[float, float]] = {
        Platform.INSTAGRAM: (0.0, 0.0),
        Platform.TIKTOK: (30.0, 90.0),
        Platform.X: (0.8, 1.6),
        Platform.THREADS: (2.0, 4.0),
        Platform.FACEBOOK: (120.0, 300.0),
        Platform.YOUTUBE: (5.0, 10.0),
        Platform.TELEGRAM: (0.3, 0.8),
        Platform.RUMBLE: (0.5, 1.0),
        Platform.REDDIT: (0.4, 0.9),
    }
    dmin, dmax = platform_defaults.get(account.platform, (3.0, 7.0))
    key = account.platform.upper()
    lo = _get_float_setting(f"REFRESH_ALL_DELAY_{key}_MIN", dmin)
    hi = _get_float_setting(f"REFRESH_ALL_DELAY_{key}_MAX", dmax)
    # Backward-compatible global clamp/fallback
    global_lo = _get_float_setting("REFRESH_ALL_DELAY_MIN", lo)
    global_hi = _get_float_setting("REFRESH_ALL_DELAY_MAX", hi)
    # REFRESH_ALL_DELAY_MIN/MAX по умолчанию 0 — это «без глобальной надстройки»,
    # а не «обнулить нижнюю границу паузы» (иначе min(..., 0) ломает джиттер платформ).
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


def _refresh_int_env(name: str, default: int, *, min_v: int = 1, max_v: int = 32) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        val = int(str(raw).strip())
    except Exception:
        return default
    return max(min_v, min(max_v, val))


def _refresh_platform_limits(accs: list[Account]) -> dict[str, int]:
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
    for p in {a.platform for a in accs}:
        env_key = f"AUTO_REFRESH_CONCURRENCY_{str(p).upper()}"
        limits[p] = _refresh_int_env(env_key, defaults.get(p, 1), min_v=1, max_v=8)
    return limits


def _interleave_accounts_by_platform(items: list[Account]) -> list[Account]:
    from .refresh_queue import interleave_accounts_by_platform

    return interleave_accounts_by_platform(items)


from .db_connections import (  # noqa: E402 — re-export for apps / tests
    ensure_fresh_db_connections,
    release_db_for_long_task,
    run_with_db_reconnect,
    stale_db_connection_error as _stale_db_connection_error,
)


def humanize_refresh_run_detail(exc: BaseException) -> str:
    """Короткий текст ошибки для run_detail / CSV (без англ. psycopg по умолчанию)."""
    if _stale_db_connection_error(exc):
        return (
            "Соединение с базой разорвано (долгий запрос или перезапуск Django). "
            "Запустите обновление снова."
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
    # 500: внутренняя ошибка съёма/БД — не «шлюз»; текст в detail для клиента и лог для сервера.
    return f"Ошибка: {exc}", status.HTTP_500_INTERNAL_SERVER_ERROR


def _refresh_account_for_api(account: Account, *, scraped: dict | None = None) -> tuple[Account | None, str | None, int | None]:
    from .refresh_cancel import RefreshCancelledError
    from .refresh_priority import account_refresh_priority_session

    try:
        with account_refresh_priority_session():
            return _refresh_with_retry(account, scraped=scraped), None, None
    except RefreshCancelledError:
        return None, "Остановлено пользователем", None
    except Exception as exc:
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
    То же, что POST /api/accounts/refresh-link-clicks/ — батч из Links API
    + кэш индекса для sync_link_clicks_for_account в _apply_refresh.
    """
    from integrations.links_client import links_api_configured
    from integrations.links_sync import begin_refresh_all_links, refresh_link_clicks_batch

    if not accounts:
        return None
    if not links_api_configured():
        print(
            f"[{log_prefix}] link clicks: skip (Links API не настроен)",
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
    for platform in sorted(used_platforms):
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
            items[i] = {**it, "status": "cancelled", "detail": "Остановлено пользователем"}
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
        state.last_error = "Аккаунты не найдены"
        state.save(update_fields=["is_running", "finished_at", "last_error", "updated_at"])
        return

    from .refresh_queue import order_accounts_for_refresh

    accounts = order_accounts_for_refresh(ordered)
    skip_recent_hours, cutoff = _schedule_skip_recent_cutoff()
    from .refresh_priority import account_refresh_priority_session

    stop_requested = threading.Event()
    state_lock = threading.Lock()
    warm_tracker = None
    try:
        with account_refresh_priority_session():
            try:
                from platforms.worker_pool import shutdown_all_workers

                shutdown_all_workers()
            except Exception:
                pass

            from .parallel_account_queue import ParallelAccountQueue
            from .refresh_all_warm import RefreshAllWarmTracker

            warm_tracker = RefreshAllWarmTracker(accounts, label="bulk_refresh")
            state.refresh_from_db(fields=["cancel_requested"])
            if state.cancel_requested:
                stop_requested.set()
                state.last_error = "Обновление остановлено пользователем."
                state.save(update_fields=["last_error", "updated_at"])
            errors_out: list[dict] = []
            import uuid

            from accounts.models import ApifyRefreshJobTrigger
            from .scrape_backend import (
                accounts_needing_playwright,
                dispatch_apify_for_batch_account,
                facebook_playwright_warm_needed,
                should_use_apify_for_account,
            )

            apify_batch_id = uuid.uuid4()
            has_facebook = facebook_playwright_warm_needed(accounts)
            fb_batch_guard = None
            if has_facebook:
                from platforms.facebook.rate_limit import FacebookRefreshBatchGuard

                fb_batch_guard = FacebookRefreshBatchGuard()

            if not stop_requested.is_set():
                from django.conf import settings as dj_settings

                pw_accounts = accounts_needing_playwright(accounts)
                if pw_accounts and bool(
                    getattr(dj_settings, "ACCOUNTS_AUTOREFRESH_PREWARM_PLAYWRIGHT", False),
                ):
                    _prewarm_workers(pw_accounts)
                preload: dict[str, dict] = {}
            else:
                preload = {}

            platform_limits = _refresh_platform_limits(accounts)
            account_queue = ParallelAccountQueue(len(accounts), platform_limits)
            worker_count = _refresh_int_env("AUTO_REFRESH_WORKERS", 1, min_v=1, max_v=16)

            with state_lock:
                state.refresh_from_db(fields=["run_detail"])
                rd = dict(state.run_detail or {})
                rd["worker_count"] = worker_count
                state.run_detail = rd
                state.save(update_fields=["run_detail", "updated_at"])

            thread_slot_map: dict[int, int] = {}
            thread_slot_lock = threading.Lock()

            def _worker_slot() -> int:
                tid = threading.get_ident()
                with thread_slot_lock:
                    if tid not in thread_slot_map:
                        thread_slot_map[tid] = len(thread_slot_map) % max(1, worker_count)
                    return thread_slot_map[tid]

            def _mark_progress(*, success: bool, failed: bool, last_error: str = "") -> None:
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

            def _worker() -> None:
                while True:
                    if stop_requested.is_set():
                        return
                    with state_lock:
                        state.refresh_from_db(fields=["cancel_requested"])
                        if bool(state.cancel_requested):
                            state.last_error = "Обновление остановлено пользователем."
                            state.save(update_fields=["last_error", "updated_at"])
                            stop_requested.set()
                            return

                    idx = account_queue.claim(
                        lambda i: accounts[i].platform,
                        stop_event=stop_requested,
                    )
                    if idx is None:
                        return

                    close_old_connections()
                    account = accounts[idx]
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
                    refresh_baseline = None
                    try:
                        if stop_requested.is_set():
                            return

                        slot = _worker_slot()
                        with state_lock:
                            state.current_account = f"{account.platform}/@{account.username}"
                            state.save(update_fields=["current_account", "updated_at"])
                        _persist_auto_refresh_run_item(account.id, status="running", worker=slot)

                        if cutoff is not None and account.updated_at and account.updated_at >= cutoff:
                            skip_detail = f"недавно обновлён (≤ {skip_recent_hours} ч)"
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
                            and not should_use_apify_for_account(account)
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
                        elif should_use_apify_for_account(account):
                            dispatch_apify_for_batch_account(
                                account,
                                trigger=ApifyRefreshJobTrigger.BULK,
                                parent_batch_id=apify_batch_id,
                            )
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
                                detail = "Остановлено пользователем"
                            if refreshed is not None:
                                _persist_auto_refresh_run_item(
                                    account.id, status="done", worker=None, detail="",
                                )
                                _mark_progress(success=True, failed=False)
                            elif detail and "Остановлен" in str(detail):
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
                                _persist_auto_refresh_run_item(
                                    account.id,
                                    status="error",
                                    worker=None,
                                    detail=err_msg[:800],
                                )
                                _mark_progress(success=False, failed=True, last_error=err_msg)
                                errors_out.append({"id": account.id, "detail": detail})
                    except RefreshCancelledError:
                        if attempted_network:
                            _restore_account_refresh_baseline(account.pk, refresh_baseline)
                        _persist_auto_refresh_run_item(
                            account.id,
                            status="cancelled",
                            worker=None,
                            detail="Остановлено пользователем",
                        )
                        _mark_progress(success=False, failed=False)
                        stop_requested.set()
                    except Exception as e:
                        if account.platform == Platform.FACEBOOK:
                            from platforms.facebook.rate_limit import (
                                is_facebook_rate_limited_error,
                                shutdown_facebook_worker,
                            )

                            if is_facebook_rate_limited_error(e):
                                shutdown_facebook_worker()
                                if fb_batch_guard is not None:
                                    fb_batch_guard.trip(str(e))
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
                            delay_sec = _refresh_all_delay_seconds(account)
                            account_queue.set_platform_cooldown(account.platform, delay_sec)
                            if account.platform == Platform.FACEBOOK and delay_sec > 0:
                                print(
                                    f"[bulk_refresh] facebook cooldown {delay_sec:.0f} с",
                                    file=sys.stderr,
                                    flush=True,
                                )
                            warm_tracker.after_network_refresh(account.platform)
                        if stop_requested.is_set():
                            account_queue.abandon(idx, account.platform)
                        else:
                            account_queue.finish(idx, account.platform)

            with ThreadPoolExecutor(max_workers=worker_count) as executor:
                futures = [executor.submit(_worker) for _ in range(worker_count)]
                for f in futures:
                    f.result()

            warm_tracker.join_warm_threads(
                timeout=15.0 if is_refresh_cancel_requested() else None,
            )

            with state_lock:
                state.refresh_from_db()
                if stop_requested.is_set():
                    _mark_bulk_refresh_queued_cancelled(state)
                if errors_out:
                    last = errors_out[-1]
                    prefix = "Остановка запрошена. " if stop_requested.is_set() else ""
                    state.last_error = (
                        f"{prefix}Ошибок: {len(errors_out)} из {len(ordered)}. "
                        f"Последняя (id={last.get('id')}): {last.get('detail', '')}"
                    )[:4000]
                    state.save(update_fields=["last_error", "updated_at"])
                elif not stop_requested.is_set():
                    state.last_error = ""
                    state.save(update_fields=["last_error", "updated_at"])
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
    """(часы из расписания, cutoff updated_at) или (0, None) если пропуск выключен."""
    cfg = RefreshScheduleConfig.get()
    try:
        cfg.refresh_from_db(fields=["skip_recent_hours"])
    except Exception:
        pass
    hours = max(0, int(getattr(cfg, "skip_recent_hours", 0) or 0))
    if hours <= 0:
        return 0, None
    return hours, timezone.now() - datetime.timedelta(hours=hours)


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
                    it["detail"] = "не обработан (остановка или прерывание)"
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
        last_error="Сбор остановлен пользователем.",
        updated_at=timezone.now(),
    )


def _refresh_all_atomic_progress(*, failed: bool, last_error: str = "") -> None:
    """Потокобезопасный счётчик прогресса без общего экземпляра модели в памяти."""
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
    После полного прохода очереди: зафиксировать сводку по ошибкам в last_error и run_detail.
    Во время прогона last_error перезаписывается последней ошибкой по аккаунту — здесь даём итог.
    """
    try:
        with transaction.atomic():
            st = RefreshAllState.objects.select_for_update().get(pk=1)
            rd = st.run_detail if isinstance(st.run_detail, dict) else {}
            rd = dict(rd)
            err_rows = [r for r in report_rows if r.get("status") == "ошибка"]
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
                    f"В ходе сбора ошибок: {failed_n}. "
                    f"Последняя ({plat}/@{uname}): {err_txt}"
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
    """Человекочитаемое локальное время (настройки Django, обычно Europe/Moscow)."""
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
    Сохраняет UTF-8 CSV отчёта последнего «собрать всех» в RefreshAllState.last_report_csv
    и метаданные прогона в run_detail['report_run'].
    """
    try:
        wall_sec = 0.0
        if run_wall_start and run_wall_end:
            wall_sec = max(0.0, (run_wall_end - run_wall_start).total_seconds())
        buffer = io.StringIO()
        writer = csv.writer(buffer, lineterminator="\n")
        headers = [
            "ID аккаунта",
            "Площадка",
            "Логин",
            "Статус",
            "Секунд на обновление",
            "Начало обновления (локальное)",
            "Конец обновления (локальное)",
            "Сохранено в БД (локальное)",
            "Подписчики",
            "Дельта подписчиков",
            "Лайки",
            "Дельта лайков",
            "Просмотры",
            "Дельта просмотров",
            "Посты",
            "Дельта постов",
            "Текст ошибки",
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
        writer.writerow(["ИТОГ прогона", "Параметр", "Значение"])
        ok_rows = sum(
            1 for r in report_rows
            if r.get("status") in ("обновилось", "нет обновлений")
        )
        meta_lines = [
            ("Начало сбора (локальное)", _refresh_all_local_dt_str(run_wall_start)),
            ("Конец сбора (локальное)", _refresh_all_local_dt_str(run_wall_end)),
            ("Всего секунд (монотонно)", str(round(run_duration_mono_sec, 3))),
            ("Всего секунд (по часам)", str(round(wall_sec, 3))),
            ("Воркеров", str(worker_count)),
            ("Строк в отчёте", str(len(report_rows))),
            ("Успешных (по строкам)", str(ok_rows)),
            ("Ошибок (по строкам)", str(sum(1 for r in report_rows if r.get("status") == "ошибка"))),
            ("Не выполнено (по строкам)", str(sum(1 for r in report_rows if r.get("status") == "не выполнено"))),
            ("Обработано (счётчик БД)", str(processed_db)),
            ("Успешно (счётчик БД)", str(success_db)),
            ("С ошибкой (счётчик БД)", str(failed_db)),
        ]
        for label, value in meta_lines:
            writer.writerow(["ИТОГ прогона", label, value])

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
            "row_error_count": sum(1 for r in report_rows if r.get("status") == "ошибка"),
            "row_skipped_count": sum(1 for r in report_rows if r.get("status") == "не выполнено"),
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
        accounts_qs = _apply_visibility_filters(
            accounts_qs,
            include_hidden_platforms=include_hidden_platforms,
            include_hidden_profiles=include_hidden_profiles,
        )
        accounts = order_accounts_for_refresh(list(accounts_qs))
        worker_count = _refresh_int_env("AUTO_REFRESH_WORKERS", 1, min_v=1, max_v=16)
        _ = download_csv  # CSV на сервере всегда; флаг только в ответе POST для совместимости

        run_items = [
            {
                "account_id": a.id,
                "platform": a.platform,
                "username": a.username,
                "status": "queued",
                "worker": None,
                "detail": "",
            }
            for a in accounts
        ]
        state.total_accounts = len(accounts)
        state.processed_accounts = 0
        state.success_accounts = 0
        state.failed_accounts = 0
        state.run_detail = {"items": run_items, "worker_count": worker_count}
        state.save(update_fields=[
            "total_accounts", "processed_accounts", "success_accounts", "failed_accounts",
            "run_detail", "updated_at",
        ])

        if not accounts:
            return

        skip_recent_hours, cutoff = _schedule_skip_recent_cutoff()

        ig_preload: dict[str, dict] = {}

        from .scrape_backend import (
            accounts_needing_playwright,
            dispatch_apify_for_batch_account,
            facebook_playwright_warm_needed,
            should_use_apify_for_account,
        )
        from accounts.models import ApifyRefreshJobTrigger

        has_facebook = facebook_playwright_warm_needed(accounts)
        fb_batch_guard = None
        if has_facebook:
            from platforms.facebook.rate_limit import FacebookRefreshBatchGuard

            fb_batch_guard = FacebookRefreshBatchGuard()

        from .refresh_priority import account_refresh_priority_session

        with account_refresh_priority_session():
            try:
                from integrations.links_sync import begin_refresh_all_links, clear_refresh_all_links

                begin_refresh_all_links(accounts)
            except Exception as e:
                print(f"[refresh_all] links preload failed: {e}", file=sys.stderr)

            from django.conf import settings as dj_settings

            pw_accounts = accounts_needing_playwright(accounts)
            if pw_accounts and bool(
                getattr(dj_settings, "ACCOUNTS_AUTOREFRESH_PREWARM_PLAYWRIGHT", False),
            ):
                _prewarm_workers(pw_accounts)

            from .parallel_account_queue import ParallelAccountQueue
            from .refresh_all_warm import RefreshAllWarmTracker

            report_lock = threading.Lock()
            stop_requested = threading.Event()

            warm_tracker = RefreshAllWarmTracker(accounts, label="refresh_all")
            if _refresh_all_cancel_requested():
                stop_requested.set()
            report_by_index: list[dict | None] = [None] * len(accounts)
            platform_limits = _refresh_platform_limits(accounts)
            account_queue = ParallelAccountQueue(len(accounts), platform_limits)

            thread_slot_map: dict[int, int] = {}
            thread_slot_lock = threading.Lock()

            def _worker_slot() -> int:
                tid = threading.get_ident()
                with thread_slot_lock:
                    if tid not in thread_slot_map:
                        thread_slot_map[tid] = len(thread_slot_map) % max(1, worker_count)
                    return thread_slot_map[tid]

            def _worker() -> None:
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
                    )
                    if idx is None:
                        return
                    close_old_connections()
                    account = accounts[idx]
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
                    refresh_baseline: dict | None = None
                    try:
                        if stop_requested.is_set():
                            return
                        if _refresh_all_cancel_requested():
                            _refresh_all_set_user_stop_message()
                            stop_requested.set()
                            return

                        slot = _worker_slot()
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
                                skip_detail = f"недавно обновлён (≤ {skip_recent_hours} ч)"
                                row = {
                                    "id": account.id,
                                    "platform": account.platform,
                                    "username": account.username,
                                    "status": "пропущен",
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
                                and not should_use_apify_for_account(account)
                                and fb_batch_guard.is_tripped()
                            ):
                                skip_detail = fb_batch_guard.skip_detail()
                                row = {
                                    "id": account.id,
                                    "platform": account.platform,
                                    "username": account.username,
                                    "status": "пропущен",
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
                            elif should_use_apify_for_account(account):
                                dispatch_apify_for_batch_account(
                                    account,
                                    trigger=ApifyRefreshJobTrigger.REFRESH_ALL,
                                    parent_batch_id=apify_batch_id,
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
                                        "status": "отменён",
                                        "follower_count": before["follower_count"],
                                        "follower_delta": 0,
                                        "like_count": before["like_count"],
                                        "like_delta": 0,
                                        "view_count": before["view_count"],
                                        "view_delta": 0,
                                        "post_count": before["post_count"],
                                        "post_delta": 0,
                                        "detail": "Остановлено пользователем",
                                    }
                                    _refresh_all_atomic_progress(failed=False)
                                    _persist_refresh_all_run_item(
                                        account.id,
                                        status="cancelled",
                                        worker=None,
                                        detail="Остановлено пользователем",
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
                                    status_label = "нет обновлений" if changed_count == 0 else "обновилось"
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
                                "status": "отменён",
                                "follower_count": before["follower_count"],
                                "follower_delta": 0,
                                "like_count": before["like_count"],
                                "like_delta": 0,
                                "view_count": before["view_count"],
                                "view_delta": 0,
                                "post_count": before["post_count"],
                                "post_delta": 0,
                                "detail": "Остановлено пользователем",
                            }
                            _refresh_all_atomic_progress(failed=False)
                            _persist_refresh_all_run_item(
                                account.id,
                                status="cancelled",
                                worker=None,
                                detail="Остановлено пользователем",
                            )
                            stop_requested.set()
                        except Exception as e:
                            if account.platform == Platform.FACEBOOK:
                                from platforms.facebook.rate_limit import (
                                    is_facebook_rate_limited_error,
                                    shutdown_facebook_worker,
                                )

                                if is_facebook_rate_limited_error(e):
                                    shutdown_facebook_worker()
                                    if fb_batch_guard is not None:
                                        fb_batch_guard.trip(str(e))
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
                            _refresh_all_atomic_progress(failed=True, last_error=str(detail or ""))
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
                            if row.get("status") not in ("ошибка", "не выполнено"):
                                row["account_db_updated_local"] = _refresh_all_local_dt_str(account.updated_at)
                            else:
                                row["account_db_updated_local"] = ""
                    finally:
                        if attempted_network and not is_refresh_cancel_requested():
                            account_queue.set_platform_cooldown(
                                account.platform,
                                _refresh_all_delay_seconds(account),
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
                futures = [executor.submit(_worker) for _ in range(worker_count)]
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
                    "status": "не выполнено",
                    "follower_count": fb,
                    "follower_delta": 0,
                    "like_count": lb,
                    "like_delta": 0,
                    "view_count": vb,
                    "view_delta": 0,
                    "post_count": pb,
                    "post_delta": 0,
                    "error": "остановка до обработки этого аккаунта",
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
            payload = _scrape(acc)
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
    # when follower counts were unavailable) — preserve existing DB stats.
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
        if is_partial and field in _STAT_FIELDS:
            continue  # don't zero-out existing stats on a partial update
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
        # Apify/парсер могут занизить heart относительно UI; не роняем лайки профиля при refresh.
        account.like_count = max(
            int(stats_before.get("like_count", 0) or 0),
            int(account.like_count or 0),
        )

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
                "Данные выглядят как ошибка или недоступность: нулевые метрики при ненулевых в базе "
                "или профиль помечен недоступным. Обновление не применено."
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
    Скрапинг один раз; запись в БД — с переподключением (после долгого worker).
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
            if "не найден" in msg or "not found" in msg:
                raise
            if not _stale_db_connection_error(exc) or attempt >= db_attempts - 1:
                raise
            time.sleep(0.4 + attempt * 0.5)
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
            "audience_list",
            "audience_member_detail",
            "audience_refresh",
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

        qs = Account.objects.select_related("profile").annotate(
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
            audience_members_count=Count("audience_memberships", distinct=True),
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
        ctx["account_delta_period_days"] = _effective_account_delta_period_days(self.request)
        return ctx

    def create(self, request, *args, **kwargs):
        """
        Импорт списка: существующий аккаунт — только смена профиля (статистика не трогаем).
        Тот же профиль — без изменений.
        """
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        validated = serializer.validated_data
        username = validated["username"]
        platform = validated["platform"]
        profile = validated.get("profile")
        new_profile_id = profile.pk if profile else None

        existing = Account.objects.filter(username=username, platform=platform).first()
        if existing is not None:
            ctx = self.get_serializer_context()
            if existing.profile_id == new_profile_id:
                data = self.get_serializer(existing, context=ctx).data
                data["import_action"] = "unchanged"
                return Response(data, status=status.HTTP_200_OK)
            existing.profile = profile
            existing.save(update_fields=["profile", "updated_at"])
            data = self.get_serializer(existing, context=ctx).data
            data["import_action"] = "profile_updated"
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
                    "detail": "Запущен сбор Apify",
                },
                status=status.HTTP_202_ACCEPTED,
            )
        with _account_refresh_mutex(account.id):
            refreshed, detail, code = _refresh_account_for_api(account)
            if refreshed is not None:
                return Response(AccountSerializer(refreshed, context=self.get_serializer_context()).data)
            return Response({"detail": detail}, status=code)

    @action(detail=False, methods=["post"], url_path="bulk-refresh")
    def bulk_refresh(self, request):
        """
        Запустить фоновое обновление выбранных аккаунтов (статус — auto-refresh-status).
        Для нескольких Instagram: один Playwright-сеанс на все /reels/ в фоновом потоке.
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

        with _refresh_all_start_lock:
            state = AutoRefreshState.get()
            rr = RefreshAllState.get()
            if state.is_running or rr.is_running:
                return Response(
                    {"detail": "Сейчас уже выполняется другое автообновление/обновление."},
                    status=status.HTTP_409_CONFLICT,
                )
            run_items = [
                {
                    "account_id": a.id,
                    "platform": a.platform,
                    "username": a.username,
                    "status": "queued",
                    "worker": None,
                    "detail": "",
                }
                for a in ordered
            ]
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
            worker_count = _refresh_int_env("AUTO_REFRESH_WORKERS", 1, min_v=1, max_v=16)
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

    @action(detail=False, methods=["post"], url_path="refresh-link-clicks")
    def refresh_link_clicks(self, request):
        """Обновить переходы (Links) для выбранных аккаунтов без scrape платформ."""
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
        by_id = {a.id: a for a in Account.objects.filter(id__in=id_ints)}
        ordered = [by_id[i] for i in id_ints if i in by_id]
        if not ordered:
            return Response({"detail": "Аккаунты не найдены"}, status=status.HTTP_404_NOT_FOUND)

        from integrations.links_client import LinksApiError, links_api_configured

        if not links_api_configured():
            return Response(
                {"detail": "Links API не настроен (LINKS_API_URL / LINKS_API_TOKEN в .env)"},
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
                {"detail": "Передайте файл в поле file"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            summary = import_snapshot_csv(upload)
        except OperationalError as e:
            if _is_deadlock_error(e):
                return Response(
                    {
                        "detail": (
                            "Импорт прерван из‑за блокировки в БД (deadlock), "
                            "обычно это параллельное обновление аккаунтов. "
                            "Подождите 10–20 с и повторите импорт."
                        ),
                    },
                    status=status.HTTP_409_CONFLICT,
                )
            return Response(
                {"detail": f"Ошибка разбора CSV: {e}"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except Exception as e:
            return Response(
                {"detail": f"Ошибка разбора CSV: {e}"},
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
                    {"detail": "Уже выполняется автообновление, сбор всех или массовое обновление."},
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

    @action(detail=True, methods=["get"], url_path="audience")
    def audience_list(self, request, pk=None):
        account = self.get_object()
        if account.platform not in AUDIENCE_SYNC_SUPPORTED_PLATFORMS:
            return Response(
                {"detail": "Аудитория доступна только для TikTok, Instagram, X и Threads."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        from .audience import audience_members_queryset_for_account

        qs = audience_members_queryset_for_account(account)
        search = (request.query_params.get("search") or "").strip()
        if search:
            qs = qs.filter(
                Q(username__icontains=search)
                | Q(display_name__icontains=search),
            )
        try:
            page = max(1, int(request.query_params.get("page") or 1))
            ps = min(100, max(1, int(request.query_params.get("page_size") or 50)))
        except (TypeError, ValueError):
            page, ps = 1, 50
        total = qs.count()
        start = (page - 1) * ps
        slice_qs = qs[start : start + ps]
        data = AudienceMemberListSerializer(slice_qs, many=True).data
        return Response({
            "count": total,
            "page": page,
            "page_size": ps,
            "results": data,
        })

    @action(
        detail=True,
        methods=["get", "delete"],
        url_path=r"audience/(?P<audience_member_id>\d+)",
    )
    def audience_member_detail(self, request, pk=None, audience_member_id=None):
        account = self.get_object()
        if account.platform not in AUDIENCE_SYNC_SUPPORTED_PLATFORMS:
            return Response(
                {"detail": "Аудитория доступна только для TikTok, Instagram, X и Threads."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        from .audience import audience_members_queryset_for_account

        if request.method == "DELETE":
            try:
                mid = int(audience_member_id)
            except (TypeError, ValueError):
                return Response(
                    {"detail": "Некорректный идентификатор подписчика."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            membership = (
                AccountAudienceMembership.objects.filter(account=account, member_id=mid)
                .select_related("member")
                .first()
            )
            if membership is None:
                return Response(
                    {"detail": "Этого подписчика нет в снятой базе для данного аккаунта."},
                    status=status.HTTP_404_NOT_FOUND,
                )
            member = membership.member
            membership.delete()
            if not member.memberships.exists():
                member.delete()
            return Response(status=status.HTTP_204_NO_CONTENT)

        base = audience_members_queryset_for_account(account)
        member = get_object_or_404(
            base.prefetch_related("audience_posts"),
            pk=int(audience_member_id),
        )
        return Response(AudienceMemberDetailSerializer(member).data)

    @action(detail=True, methods=["post"], url_path="audience/refresh")
    def audience_refresh(self, request, pk=None):
        account = self.get_object()
        if account.platform not in AUDIENCE_SYNC_SUPPORTED_PLATFORMS:
            return Response(
                {"detail": "Съём аудитории поддерживается только для TikTok, Instagram, X и Threads."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        from .refresh_priority import PRIORITY_BLOCK_MESSAGE, account_refresh_priority_active

        if account_refresh_priority_active():
            return Response(
                {"detail": PRIORITY_BLOCK_MESSAGE},
                status=status.HTTP_409_CONFLICT,
            )
        from .audience import normalize_audience_mode, refresh_audience_for_account

        from .audience import _normalize_enrich_usernames

        skip = False
        mode = "full"
        enrich_usernames = None
        body = getattr(request, "data", None)
        if isinstance(body, dict):
            skip = bool(body.get("skip_existing_member_profiles"))
            if body.get("audience_mode") is not None:
                mode = normalize_audience_mode(body.get("audience_mode"))
            if body.get("enrich_usernames") is not None:
                enrich_usernames = _normalize_enrich_usernames(body.get("enrich_usernames"))

        try:
            result = refresh_audience_for_account(
                account,
                audience_mode=mode,
                skip_existing_member_profiles=skip,
                enrich_usernames=enrich_usernames,
            )
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as exc:
            logger.exception("audience_refresh failed", extra={"account_id": account.id})
            return Response(
                {"detail": f"Ошибка съёма аудитории: {exc}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
        return Response(result)


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
            # Нет снимка не старше cutoff — считаем baseline нулевым: весь текущий счётчик
            # участвует в дельте (актуально для окна 30д и «молодых» аккаунтов).
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

    return Response({
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


def _clamp_max_audience_followers_saved(raw) -> int:
    """1 … MAX — лимит подписчиков на один отслеживаемый Account (хранится в БД)."""
    cap = MAX_AUDIENCE_FOLLOWERS_PER_TRACKED_ACCOUNT
    try:
        v = int(raw)
    except (TypeError, ValueError):
        return cap
    return max(1, min(cap, v))


def _telegram_bot_configured() -> bool:
    from .telegram_report import telegram_bot_configured

    return telegram_bot_configured()


def _telegram_default_chat_id() -> str:
    from django.conf import settings

    return (getattr(settings, "TELEGRAM_AUTO_REFRESH_CHAT_ID", None) or "").strip()


def _schedule_to_dict(config) -> dict:
    from .auto_refresh_scope import (
        normalize_auto_refresh_platforms,
        normalize_auto_refresh_profile_ids,
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
        "auto_refresh_csv_report": True,
        "auto_refresh_telegram_enabled": bool(
            getattr(config, "auto_refresh_telegram_enabled", False),
        ),
        "auto_refresh_telegram_chat_id": (
            getattr(config, "auto_refresh_telegram_chat_id", None) or ""
        ).strip(),
        "telegram_bot_configured": _telegram_bot_configured(),
        "telegram_chat_configured": bool(
            (getattr(config, "auto_refresh_telegram_chat_id", None) or "").strip()
            or _telegram_default_chat_id()
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
        "account_delta_period_days": (
            d if (d := int(getattr(config, "account_delta_period_days", 1) or 1)) in (1, 7, 30) else 1
        ),
        "max_audience_followers_per_account": _clamp_max_audience_followers_saved(
            getattr(
                config,
                "max_audience_followers_per_account",
                MAX_AUDIENCE_FOLLOWERS_PER_TRACKED_ACCOUNT,
            ),
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
def tv_emu_config(request):
    """
    Настройки TV-эмуляции (Atomic): общий JSON для всех браузеров/устройств.
    GET — { "config": object | null }; POST — { "config": object }.
    """
    from .tv_emu_config import (
        bump_tv_emu_runtime_epoch,
        load_tv_emu_config,
        load_tv_emu_runtime_epoch,
        save_tv_emu_config,
    )

    if request.method == "GET":
        stored = load_tv_emu_config()
        return Response({
            "config": stored,
            "runtime_epoch": load_tv_emu_runtime_epoch(),
            "source": "server",
            "updated": bool(stored),
        })

    data = request.data if isinstance(request.data, dict) else {}
    config = data.get("config")
    if not isinstance(config, dict):
        return Response(
            {"error": "Ожидается JSON-объект в поле config"},
            status=drf_status.HTTP_400_BAD_REQUEST,
        )
    try:
        path = save_tv_emu_config(config)
    except ValueError as exc:
        return Response({"error": str(exc)}, status=drf_status.HTTP_400_BAD_REQUEST)
    runtime_epoch = load_tv_emu_runtime_epoch()
    if data.get("restart") is True:
        runtime_epoch = bump_tv_emu_runtime_epoch()
    return Response({
        "ok": True,
        "message": "Настройки эмуляции сохранены на сервере",
        "config_path": str(path),
        "runtime_epoch": runtime_epoch,
    })


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
        if "auto_refresh_telegram_chat_id" in data:
            config.auto_refresh_telegram_chat_id = str(
                data.get("auto_refresh_telegram_chat_id") or "",
            ).strip()[:32]
        if "include_hidden_platform_accounts" in data:
            config.include_hidden_platform_accounts = _coerce_bool(data["include_hidden_platform_accounts"])
        if "include_hidden_profile_accounts" in data:
            config.include_hidden_profile_accounts = _coerce_bool(data["include_hidden_profile_accounts"])
        if "include_unavailable_accounts" in data:
            config.include_unavailable_accounts = _coerce_bool(data["include_unavailable_accounts"])
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
        if "account_delta_period_days" in data:
            raw = int(data["account_delta_period_days"])
            config.account_delta_period_days = raw if raw in (1, 7, 30) else 1
        if "max_audience_followers_per_account" in data:
            config.max_audience_followers_per_account = _clamp_max_audience_followers_saved(
                data["max_audience_followers_per_account"],
            )
        config.save()

        sched = get_scheduler()
        if sched is not None:
            sync_schedule_from_db(force=True)
        else:
            print(
                "[scheduler] POST /schedule/: планировщик не запущен — "
                "слоты по времени не сработают. Перезапустите runserver.",
                file=sys.stderr,
                flush=True,
            )

        return Response(_schedule_to_dict(config))
    except (ProgrammingError, OperationalError) as exc:
        return _schedule_db_error_response(exc)


@api_view(["POST"])
def auto_refresh_telegram_test(request):
    """Проверка TELEGRAM_BOT_TOKEN и chat_id (тестовое сообщение)."""
    try:
        from .models import RefreshScheduleConfig
        from .telegram_report import send_telegram_test_message

        config = RefreshScheduleConfig.get()
        data = request.data if isinstance(request.data, dict) else {}
        chat_id = str(data.get("chat_id") or "").strip() or None
        send_telegram_test_message(config=config, chat_id=chat_id)
        return Response({"ok": True, "detail": "Сообщение отправлено в Telegram."})
    except Exception as exc:
        return Response(
            {"ok": False, "detail": str(exc)},
            status=status.HTTP_400_BAD_REQUEST,
        )


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
    """
    Статус фонового обновления (авто + refresh_all). Сбрасывает зависший is_running по таймауту.
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

        if auto.is_running:
            state = auto
            auto_src = (getattr(auto, "source", None) or "").strip()
            pipeline = "bulk_refresh" if auto_src == "bulk_refresh" else "scheduled_auto"
        elif rr.is_running:
            state = rr
            pipeline = "refresh_all"
        else:
            state = auto
            pipeline = None

        total = max(0, int(state.total_accounts or 0))
        done = max(0, int(state.processed_accounts or 0))
        progress = 0 if total <= 0 else min(100, int(round((done / total) * 100)))
        report_csv = (getattr(auto, "last_report_csv", None) or "").strip()
        rd = _coerce_rd(state) if pipeline else _coerce_rd(auto)
        resp_src = (getattr(state, "source", None) or "").strip()
        if pipeline == "refresh_all" and not resp_src:
            resp_src = "refresh_all"
        from .apps import peek_pending_scheduled_refresh_count

        pending = peek_pending_scheduled_refresh_count()
        return Response({
            "is_running": bool(auto.is_running or rr.is_running),
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

        clear_stale_refresh_runs_if_needed()
        state = AutoRefreshState.get()
        rr = RefreshAllState.get()
        if state.is_running or rr.is_running:
            return Response(
                {"started": False, "detail": "Автообновление или сбор всех уже выполняется."},
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
    """Сбросить зависший is_running (после warm_tiktok, сбоя воркеров). body/query: force=1."""
    try:
        from .refresh_state import clear_stale_refresh_runs_if_needed, clear_stuck_refresh_run

        raw = request.data.get("force") if hasattr(request, "data") else None
        if raw is None:
            raw = request.query_params.get("force")
        force = str(raw or "").strip().lower() in {"1", "true", "yes", "on"}
        if force:
            cleared = clear_stuck_refresh_run(
                reason="Сброшено вручную (API auto-refresh-reset-state).",
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
            return Response({"stopped": False, "detail": "Автообновление сейчас не выполняется."}, status=status.HTTP_409_CONFLICT)
        from .refresh_state import force_stop_auto_refresh
        from platforms.apify.abort import abort_active_apify_jobs

        force_stop_auto_refresh(reason="Остановлено пользователем.")
        abort_active_apify_jobs()
        state.refresh_from_db(fields=["is_running", "cancel_requested", "current_account", "updated_at"])
        return Response(
            {
                "stopped": True,
                "is_running": bool(state.is_running),
                "detail": (
                    "Остановка принята. Статус сброшен; браузеры закрываются в фоне. "
                    "Обновите страницу, если кнопка ещё «Остановка…»."
                ),
            },
        )
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


@api_view(["GET"])
def auto_refresh_last_error_ids(request):
    """ID аккаунтов со статусом «ошибка» в последнем завершённом автообновлении по расписанию."""
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
    """Статус фонового POST /api/accounts/refresh_all/ (очередь, слоты воркеров)."""
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
    """Запросить остановку текущего сбора всех аккаунтов."""
    try:
        st = RefreshAllState.get()
        if not st.is_running:
            return Response(
                {"stopped": False, "detail": "Сбор всех аккаунтов сейчас не выполняется."},
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


@api_view(["POST"])
def audience_scrape_stop(_request):
    """
    Прервать текущий съём аудитории Playwright (одиночный POST audience/refresh или запрос из subs).
    Закрывает демоны worker и Chromium профиля AccountsStats.
    """
    try:
        from platforms.worker_pool import shutdown_playwright_pool_aggressive

        shutdown_playwright_pool_aggressive()
        return Response({"stopped": True})
    except Exception as exc:
        logger.exception("audience_scrape_stop failed")
        return Response(
            {"detail": f"Не удалось остановить съём аудитории: {exc}"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


@api_view(["GET"])
def refresh_all_report_download(request):
    """Скачать CSV отчёта последнего завершённого сбора всех (GET /api/accounts/refresh-all-report/)."""
    try:
        st = RefreshAllState.get()
        body = (getattr(st, "last_report_csv", None) or "").strip()
        if not body:
            return Response(
                {
                    "detail": (
                        "Отчёт ещё не сформирован. Запустите сбор всех аккаунтов "
                        "и дождитесь завершения — CSV сохранится на сервере автоматически."
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
    Аватар: локальный файл, иначе прокси avatar_url (CDN).
    GET /api/accounts/<pk>/avatar/
    """
    from .avatar_storage import serve_account_avatar_response

    return serve_account_avatar_response(pk)


def post_thumbnail(request, pk: int):
    """
    Превью поста: локальный файл, иначе прокси thumbnail_url (CDN).
    GET /api/posts/<pk>/thumbnail/
    """
    from .post_thumbnail_storage import serve_post_thumbnail_response

    return serve_post_thumbnail_response(pk)
