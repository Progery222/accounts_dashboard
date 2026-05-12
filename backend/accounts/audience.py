"""
Съём и сохранение аудитории (подписчики) для TikTok, Instagram, X и Threads.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path

from django.db import transaction
from django.db.models import Count, Q
from django.utils import dateparse
from django.utils import timezone

from .constants import (
    MAX_AUDIENCE_FOLLOWERS_PER_TRACKED_ACCOUNT,
    MAX_AUDIENCE_POSTS_PER_MEMBER,
)
from .models import (
    Account,
    AccountAudienceMembership,
    AudienceMember,
    AudienceMemberPost,
    Platform,
    RefreshScheduleConfig,
)

logger = logging.getLogger(__name__)

_TIKTOK_WORKER = Path(__file__).resolve().parent.parent / "platforms" / "tiktok" / "worker.py"
_INSTAGRAM_WORKER = Path(__file__).resolve().parent.parent / "platforms" / "instagram" / "worker.py"
_X_WORKER = Path(__file__).resolve().parent.parent / "platforms" / "x" / "worker.py"
_THREADS_WORKER = Path(__file__).resolve().parent.parent / "platforms" / "threads" / "worker.py"


def effective_audience_follower_limit() -> int:
    cfg = RefreshScheduleConfig.get()
    v = int(getattr(cfg, "max_audience_followers_per_account", 100) or 100)
    return max(1, min(MAX_AUDIENCE_FOLLOWERS_PER_TRACKED_ACCOUNT, v))


def fetch_audience_payload(account: Account, *, skip_existing_member_profiles: bool = False) -> dict:
    """Синхронный вызов Playwright worker; может занять много времени."""
    from platforms.worker_pool import call_worker, ensure_worker

    lim = effective_audience_follower_limit()
    # 0 — не ходить на профиль каждого подписчика ради скролла сетки постов (ускорение, меньше антибота).
    payload = {
        "audience_followers": True,
        "username": account.username,
        "limit": lim,
        "max_posts_per_follower": 0,
        "audience_account_id": account.pk,
        "skip_existing_member_profiles": bool(skip_existing_member_profiles),
    }
    if account.platform == Platform.TIKTOK:
        ensure_worker(_TIKTOK_WORKER)
        return call_worker(_TIKTOK_WORKER, payload, timeout_sec=900.0)
    if account.platform == Platform.INSTAGRAM:
        ensure_worker(_INSTAGRAM_WORKER)
        return call_worker(_INSTAGRAM_WORKER, payload, timeout_sec=900.0)
    if account.platform == Platform.X:
        ensure_worker(_X_WORKER)
        return call_worker(_X_WORKER, payload, timeout_sec=900.0)
    if account.platform == Platform.THREADS:
        ensure_worker(_THREADS_WORKER)
        return call_worker(_THREADS_WORKER, payload, timeout_sec=900.0)
    raise ValueError("Съём аудитории поддерживается только для TikTok, Instagram, X и Threads.")


def _to_int(v) -> int:
    if v is None:
        return 0
    if isinstance(v, (int, float)):
        return int(v)
    s = str(v).strip().replace("\u00a0", "").replace("\u202f", "").replace(" ", "")
    digits = re.sub(r"[^\d]", "", s)
    return int(digits) if digits else 0


@transaction.atomic
def sync_audience_from_payload(account: Account, payload: dict) -> dict:
    """
    Сохранить подписчиков и посты. Список считается полным срезом последнего съёма:
    связи account↔member, отсутствующие в payload, удаляются.
    """
    if not isinstance(payload, dict):
        raise ValueError("Некорректный ответ съёма аудитории.")
    if payload.get("error"):
        raise ValueError(str(payload["error"]))

    rows = payload.get("followers")
    if not isinstance(rows, list):
        raise ValueError("В ответе worker нет списка followers.")

    lim = effective_audience_follower_limit()
    rows = rows[:lim]

    platform = account.platform
    kept_member_ids: list[int] = []

    for raw in rows:
        if not isinstance(raw, dict):
            continue
        uname = str(raw.get("username") or "").strip().lstrip("@").lower()[:255]
        if not uname:
            continue
        if raw.get("_reuse_existing"):
            member = AudienceMember.objects.filter(platform=platform, username=uname).first()
            if member:
                AccountAudienceMembership.objects.update_or_create(
                    account=account,
                    member=member,
                    defaults={},
                )
                kept_member_ids.append(member.id)
            continue
        ext = str(raw.get("external_id") or "")[:160]
        defaults = {
            "external_id": ext,
            "display_name": str(raw.get("display_name") or "")[:255],
            "avatar_url": str(raw.get("avatar_url") or "")[:2048],
            "bio": str(raw.get("bio") or "")[:4000],
            "is_private": bool(raw.get("is_private")),
            "follower_count": _to_int(raw.get("follower_count")),
            "following_count": _to_int(raw.get("following_count")),
            "like_count": _to_int(raw.get("like_count")),
            "profile_language": str(raw.get("profile_language") or "")[:32],
            "timezone_name": str(raw.get("timezone_name") or "")[:64],
        }
        member, _ = AudienceMember.objects.update_or_create(
            platform=platform,
            username=uname,
            defaults=defaults,
        )
        AccountAudienceMembership.objects.update_or_create(
            account=account,
            member=member,
            defaults={},
        )
        kept_member_ids.append(member.id)

        posts = raw.get("posts")
        if isinstance(posts, list) and posts:
            AudienceMemberPost.objects.filter(member=member).delete()
            bulk: list[AudienceMemberPost] = []
            for pd in posts[:MAX_AUDIENCE_POSTS_PER_MEMBER]:
                if not isinstance(pd, dict):
                    continue
                eid = str(pd.get("external_id") or "").strip()[:255]
                if not eid:
                    continue
                posted_at = None
                if pd.get("posted_at"):
                    posted_at = dateparse.parse_datetime(str(pd["posted_at"]))
                bulk.append(
                    AudienceMemberPost(
                        member=member,
                        external_id=eid,
                        description=str(pd.get("description") or "")[:4000],
                        thumbnail_url=str(pd.get("thumbnail_url") or "")[:2048],
                        post_url=str(pd.get("post_url") or "")[:2048],
                        view_count=_to_int(pd.get("view_count")),
                        like_count=_to_int(pd.get("like_count")),
                        comment_count=_to_int(pd.get("comment_count")),
                        share_count=_to_int(pd.get("share_count")),
                        posted_at=posted_at,
                    ),
                )
            if bulk:
                AudienceMemberPost.objects.bulk_create(bulk)

    AccountAudienceMembership.objects.filter(account=account).exclude(
        member_id__in=kept_member_ids or [0],
    ).delete()

    account.audience_last_synced_at = timezone.now()
    account.save(update_fields=["audience_last_synced_at", "updated_at"])

    return {
        "followers_saved": len(kept_member_ids),
        "synced_at": account.audience_last_synced_at.isoformat(),
    }


def refresh_audience_for_account(account: Account, *, skip_existing_member_profiles: bool = False) -> dict:
    payload = fetch_audience_payload(
        account,
        skip_existing_member_profiles=skip_existing_member_profiles,
    )
    return sync_audience_from_payload(account, payload)


def audience_members_queryset_for_account(account: Account):
    tracked_ids = list(Account.objects.values_list("pk", flat=True))
    return (
        AudienceMember.objects.filter(memberships__account=account)
        .annotate(
            follows_tracked_accounts_count=Count(
                "memberships",
                filter=Q(memberships__account_id__in=tracked_ids),
                distinct=True,
            ),
        )
        .order_by("username")
        .distinct()
    )
