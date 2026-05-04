import datetime
import random
import re
import sys
import threading
import time
from pathlib import Path
import httpx
import io
import csv
from django.conf import settings
from django.http import HttpResponse
from django.utils import timezone
from django.db.models import Sum
from rest_framework import viewsets, status
from rest_framework.decorators import api_view, action
from rest_framework.parsers import JSONParser, MultiPartParser
from rest_framework.response import Response
from django.db.models import Q
from .models import Account, Platform, Post, Profile
from .serializers import AccountSerializer, PostSerializer, ProfileSerializer
from .snapshot_io import build_snapshot_csv, import_snapshot_csv
from platforms.profile_unavailable import (
    is_profile_unavailable_error,
    user_visible_profile_unavailable_error,
)


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

    raise ValueError(f"Обновление для «{platform}» не поддерживается.")


def _sync_posts(account: Account, posts_data: list) -> None:
    today = timezone.now().date()
    seen_external_ids: set[str] = set()

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
        post.view_count = _to_int(pd.get("view_count", pd.get("play_count", 0)))
        post.like_count = _to_int(pd.get("like_count", pd.get("digg_count", 0)))
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


def _prewarm_workers(accounts: list[Account]) -> None:
    """
    Start daemon workers upfront for platforms present in refresh_all batch.
    This opens one browser window per used platform at the beginning.
    """
    from platforms.worker_pool import ensure_worker

    workers_by_platform = {
        Platform.TIKTOK:   Path(__file__).parent.parent / "platforms" / "tiktok" / "worker.py",
        Platform.INSTAGRAM: Path(__file__).parent.parent / "platforms" / "instagram" / "worker.py",
        Platform.X:        Path(__file__).parent.parent / "platforms" / "x" / "worker.py",
        Platform.THREADS:  Path(__file__).parent.parent / "platforms" / "threads" / "worker.py",
        Platform.FACEBOOK: Path(__file__).parent.parent / "platforms" / "facebook" / "worker.py",
        Platform.TELEGRAM: Path(__file__).parent.parent / "platforms" / "telegram" / "worker.py",
        Platform.RUMBLE:   Path(__file__).parent.parent / "platforms" / "rumble" / "worker.py",
    }
    used_platforms = {acc.platform for acc in accounts}
    for platform in used_platforms:
        worker = workers_by_platform.get(platform)
        if not worker:
            continue
        if worker.exists():
            try:
                ensure_worker(worker)
            except Exception as e:
                print(f"[prewarm] failed for {platform}: {e}")


def _apply_refresh(account: Account, scraped: dict | None = None) -> Account:
    snap, _ = account.take_snapshot_if_needed()
    # Копия, чтобы .pop() не портил кэш preload при нескольких IG подряд.
    data = dict(scraped) if scraped is not None else _scrape(account)
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
            setattr(account, field, value)
    account.save()

    if has_posts_key and (posts_authoritative or posts):
        try:
            _sync_posts(account, posts)
        except Exception as e:
            print(f"[posts] sync error for @{account.username}: {e}")
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
        Platform.X, Platform.THREADS, Platform.RUMBLE,
    ):
        account.like_count = agg["total_likes"] or 0
    # If the scraper didn't return a post_count (returned 0/None), fall back to
    # the number of posts we actually have stored — better than showing a dash.
    stored_post_count = account.posts.count()
    if not account.post_count and stored_post_count:
        account.post_count = stored_post_count
    account.save(update_fields=["view_count", "like_count", "post_count"])

    # Keep today's snapshot up-to-date with the freshly-scraped/aggregated values.
    # This is the baseline used by tomorrow's delta calculation.
    snap.follower_count = account.follower_count
    snap.like_count = account.like_count
    snap.view_count = account.view_count
    snap.post_count = account.post_count
    snap.save(update_fields=[
        "follower_count", "like_count", "view_count", "post_count",
    ])

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
        Platform.X, Platform.THREADS, Platform.RUMBLE,
    ):
        account.snapshots.filter(
            date__lt=snap.date,
            like_count=0,
        ).update(like_count=account.like_count)

    return account


class AccountViewSet(viewsets.ModelViewSet):
    serializer_class = AccountSerializer

    def get_queryset(self):
        qs = Account.objects.select_related("profile").all()
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
        return qs

    @action(detail=True, methods=["post"])
    def refresh(self, request, pk=None):
        account = self.get_object()
        with _account_refresh_mutex(account.id):
            try:
                account = _apply_refresh(account)
                return Response(AccountSerializer(account).data)
            except ValueError as e:
                _mark_profile_unavailable_if_applicable(account, e)
                return Response(
                    {"detail": user_visible_profile_unavailable_error(str(e))},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            except Exception as e:
                return Response({"detail": f"Ошибка: {e}"}, status=status.HTTP_502_BAD_GATEWAY)

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
        def _ig_preload_key(username: str) -> str:
            # Должно совпадать с norm() в platforms.instagram.scraper.fetch_instagram_profiles_bulk
            return (username or "").lstrip("@").strip().lower()

        for a in ordered:
            try:
                with _account_refresh_mutex(a.id):
                    key = _ig_preload_key(a.username)
                    if (
                        a.platform == Platform.INSTAGRAM
                        and len(ig_accounts) > 1
                        and key in preload
                    ):
                        account = _apply_refresh(a, scraped=preload[key])
                    else:
                        account = _apply_refresh(a)
                accounts_out.append(AccountSerializer(account).data)
            except ValueError as e:
                _mark_profile_unavailable_if_applicable(a, e)
                errors_out.append({"id": a.id, "detail": user_visible_profile_unavailable_error(str(e))})
            except Exception as e:
                errors_out.append({"id": a.id, "detail": f"Ошибка: {e}"})

        return Response({"accounts": accounts_out, "errors": errors_out})

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
        accounts = list(Account.objects.all().order_by("platform", "id"))
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

        for idx, account in enumerate(accounts):
            before = {
                "follower_count": account.follower_count,
                "like_count": account.like_count,
                "view_count": account.view_count,
                "post_count": account.post_count,
            }
            try:
                ig_key = (account.username or "").lower()
                if (
                    account.platform == Platform.INSTAGRAM
                    and len(ig_all) > 1
                    and ig_key in ig_preload
                ):
                    _apply_refresh(account, scraped=ig_preload[ig_key])
                else:
                    _apply_refresh(account)
                account.refresh_from_db(fields=["follower_count", "like_count", "view_count", "post_count"])
                after = {
                    "follower_count": account.follower_count,
                    "like_count": account.like_count,
                    "view_count": account.view_count,
                    "post_count": account.post_count,
                }
                changed = {k: (after[k] != before[k]) for k in before}
                changed_count = sum(1 for v in changed.values() if v)
                if changed_count == len(changed):
                    status_label = "обновилось успешно"
                elif changed_count == 0:
                    status_label = "нет обновлений"
                else:
                    status_label = "обновилось не полностью"

                report_rows.append({
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
                })
                refreshed += 1
            except Exception as e:
                failed += 1
                _mark_profile_unavailable_if_applicable(account, e)
                err_msg = user_visible_profile_unavailable_error(str(e)) if isinstance(e, ValueError) else str(e)
                errors.append(f"@{account.username} ({account.platform}): {err_msg}")
                report_rows.append({
                    "id": account.id,
                    "platform": account.platform,
                    "username": account.username,
                    "status": "ошибка",
                    "error": err_msg,
                    "follower_count": before["follower_count"],
                    "follower_delta": None,
                    "like_count": before["like_count"],
                    "like_delta": None,
                    "view_count": before["view_count"],
                    "view_delta": None,
                    "post_count": before["post_count"],
                    "post_delta": None,
                })

            if idx < len(accounts) - 1:
                lo = float(getattr(settings, "REFRESH_ALL_DELAY_MIN", 0) or 0)
                hi = float(getattr(settings, "REFRESH_ALL_DELAY_MAX", 0) or 0)
                if hi > 0:
                    a = max(0.0, min(lo, hi))
                    b = max(lo, hi)
                    time.sleep(random.uniform(a, b))

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
        qs = account.posts.prefetch_related("snapshots").all()
        return Response(PostSerializer(qs, many=True).data)


class ProfileViewSet(viewsets.ModelViewSet):
    serializer_class = ProfileSerializer
    queryset = Profile.objects.all()

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
    data = [{"value": v, "label": l} for v, l in Platform.choices]
    return Response(data)


@api_view(["GET"])
def summary(request):
    """Aggregate stats + deltas across all accounts, grouped by platform."""
    today = timezone.now().date()
    accounts = list(Account.objects.prefetch_related("snapshots").all())

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
        "by_platform": list(by_platform.values()),
    })


def _schedule_to_dict(config) -> dict:
    return {
        "enabled": config.enabled,
        "mode": config.mode,
        "interval_hours": config.interval_hours,
        "times": config.times,
    }


@api_view(["GET", "POST"])
def refresh_schedule(request):
    """Get or update the auto-refresh schedule config."""
    from .models import RefreshScheduleConfig
    from .apps import get_scheduler, apply_schedule_config

    config = RefreshScheduleConfig.get()

    if request.method == "GET":
        return Response(_schedule_to_dict(config))

    data = request.data
    if "enabled" in data:
        config.enabled = bool(data["enabled"])
    if "mode" in data and data["mode"] in ("interval", "times"):
        config.mode = data["mode"]
    if "interval_hours" in data:
        config.interval_hours = max(1, min(24, int(data["interval_hours"])))
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
        # TikTok sometimes hides/rotates profile avatar URLs; use the first post
        # cover as a stable fallback avatar source.
        first_post = account.posts.exclude(thumbnail_url="").order_by("-updated_at").first()
        if first_post:
            url = first_post.thumbnail_url
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
