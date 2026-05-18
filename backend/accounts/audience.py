"""
Съём и сохранение аудитории (подписчики) для TikTok, Instagram, X и Threads (Playwright-воркеры).

Режимы (``audience_mode``):
- ``list`` — только список подписчиков отслеживаемого аккаунта (модалка / лента);
- ``enrich`` — обновление профилей уже сохранённых подписчиков (без prune отписок);
- ``full`` — list + enrich за один проход (поведение по умолчанию, как раньше).
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

_AUDIENCE_WORKER_BY_PLATFORM: dict[str, Path] = {
    Platform.TIKTOK: _TIKTOK_WORKER,
    Platform.INSTAGRAM: _INSTAGRAM_WORKER,
    Platform.X: _X_WORKER,
    Platform.THREADS: _THREADS_WORKER,
}

AUDIENCE_SYNC_SUPPORTED_PLATFORMS: frozenset[str] = frozenset(_AUDIENCE_WORKER_BY_PLATFORM.keys())
AUDIENCE_MODES: frozenset[str] = frozenset({"list", "enrich", "full"})


def normalize_audience_mode(raw: str | None) -> str:
    mode = str(raw or "full").strip().lower()
    if mode not in AUDIENCE_MODES:
        raise ValueError(
            f"Недопустимый audience_mode: {raw!r}. Допустимо: list, enrich, full.",
        )
    return mode


def effective_audience_follower_limit() -> int:
    cfg = RefreshScheduleConfig.get()
    v = int(getattr(cfg, "max_audience_followers_per_account", 100) or 100)
    return max(1, min(MAX_AUDIENCE_FOLLOWERS_PER_TRACKED_ACCOUNT, v))


def _normalize_enrich_usernames(raw) -> list[str] | None:
    if raw is None:
        return None
    if not isinstance(raw, (list, tuple)):
        raise ValueError("enrich_usernames должен быть массивом ников.")
    out: list[str] = []
    for item in raw:
        u = str(item or "").strip().lstrip("@").lower()
        if u:
            out.append(u)
    return out or None


def fetch_audience_payload(
    account: Account,
    *,
    audience_mode: str = "full",
    skip_existing_member_profiles: bool = False,
    enrich_usernames: list[str] | None = None,
) -> dict:
    """Синхронный вызов Playwright worker; может занять много времени."""
    from .audience_platform_gate import audience_platform_slot
    from .refresh_priority import PRIORITY_BLOCK_MESSAGE, account_refresh_priority_active
    from platforms.worker_pool import call_worker, ensure_worker

    if account_refresh_priority_active():
        raise ValueError(PRIORITY_BLOCK_MESSAGE)

    mode = normalize_audience_mode(audience_mode)
    lim = effective_audience_follower_limit()
    payload = {
        "audience_followers": True,
        "username": account.username,
        "limit": lim,
        "max_posts_per_follower": 0,
        "audience_account_id": account.pk,
        "audience_mode": mode,
        "list_only": mode == "list",
        "enrich_only": mode == "enrich",
        "skip_existing_member_profiles": bool(skip_existing_member_profiles),
    }
    if enrich_usernames:
        payload["enrich_usernames"] = list(enrich_usernames)
    worker_script = _AUDIENCE_WORKER_BY_PLATFORM.get(account.platform)
    if worker_script is None:
        raise ValueError(
            "Съём аудитории поддерживается только для TikTok, Instagram, X и Threads.",
        )
    if mode == "enrich":
        linked = AudienceMember.objects.filter(memberships__account=account).count()
        if linked < 1:
            raise ValueError(
                "Нет сохранённых подписчиков для обогащения — сначала выполните съём списка (режим list).",
            )
    with audience_platform_slot(account.platform):
        if account_refresh_priority_active():
            raise ValueError(PRIORITY_BLOCK_MESSAGE)
        ensure_worker(worker_script)
        out = call_worker(worker_script, payload, timeout_sec=3600.0)
    if isinstance(out, dict):
        out.setdefault("audience_mode", mode)
    return out


def _to_int(v) -> int:
    if v is None:
        return 0
    if isinstance(v, (int, float)):
        return int(v)
    s = str(v).strip().replace("\u00a0", "").replace("\u202f", "").replace(" ", "")
    digits = re.sub(r"[^\d]", "", s)
    return int(digits) if digits else 0


def _sanitize_follower_network(val) -> list:
    if not isinstance(val, list):
        return []
    out: list[dict] = []
    for it in val:
        if len(out) >= 100:
            break
        if not isinstance(it, dict):
            continue
        u = str(it.get("username") or "").strip().lstrip("@").lower()[:255]
        if not u:
            continue
        out.append(
            {
                "username": u,
                "display_name": str(it.get("display_name") or "")[:255],
                "avatar_url": str(it.get("avatar_url") or "")[:2048],
                "bio": str(it.get("bio") or "")[:2000],
                "is_private": bool(it.get("is_private")),
                "follower_count": _to_int(it.get("follower_count")),
                "following_count": _to_int(it.get("following_count")),
                "like_count": _to_int(it.get("like_count")),
            },
        )
    return out


def _patch_member_from_row_nondestructive(member: AudienceMember, raw: dict) -> None:
    """Обновить поля, не затирая ненулевые значения пустыми (режим list)."""
    patch_fields: list[str] = []
    ndisp = str(raw.get("display_name") or "").strip()[:255]
    if ndisp and ndisp != (member.display_name or "").strip():
        member.display_name = ndisp
        patch_fields.append("display_name")
    nbio = str(raw.get("bio") or "").strip()[:4000]
    if nbio and nbio != (member.bio or "").strip():
        member.bio = nbio
        patch_fields.append("bio")
    nav = str(raw.get("avatar_url") or "").strip()[:2048]
    if nav and nav != (member.avatar_url or "").strip():
        member.avatar_url = nav
        patch_fields.append("avatar_url")
    if raw.get("is_private") is not None and bool(raw.get("is_private")) != bool(member.is_private):
        member.is_private = bool(raw.get("is_private"))
        patch_fields.append("is_private")
    ext = str(raw.get("external_id") or "").strip()[:160]
    if ext and ext != (member.external_id or "").strip():
        member.external_id = ext
        patch_fields.append("external_id")
    for ck in ("follower_count", "following_count", "like_count"):
        nv = _to_int(raw.get(ck))
        ov = int(getattr(member, ck) or 0)
        if nv > 0 and nv != ov:
            setattr(member, ck, nv)
            patch_fields.append(ck)
    pl = str(raw.get("profile_language") or "").strip()[:32]
    if pl and pl != (member.profile_language or "").strip():
        member.profile_language = pl
        patch_fields.append("profile_language")
    tz = str(raw.get("timezone_name") or "").strip()[:64]
    if tz and tz != (member.timezone_name or "").strip():
        member.timezone_name = tz
        patch_fields.append("timezone_name")
    if patch_fields:
        member.save(update_fields=patch_fields + ["updated_at"])


def _enrich_member_summary(raw: dict) -> dict:
    """Краткая сводка по подписчику для ответа API (режим enrich)."""
    bio = str(raw.get("bio") or "").strip()
    note = str(raw.get("_enrich_note") or raw.get("_enrich_error") or "").strip()[:200]
    ok = raw.get("_enrich_ok")
    if ok is None:
        ok = bool(
            str(raw.get("display_name") or "").strip()
            or _to_int(raw.get("follower_count")) > 0
            or len(bio) > 2
        )
    return {
        "username": str(raw.get("username") or "").strip().lstrip("@").lower(),
        "display_name": str(raw.get("display_name") or "")[:255],
        "follower_count": _to_int(raw.get("follower_count")),
        "following_count": _to_int(raw.get("following_count")),
        "like_count": _to_int(raw.get("like_count")),
        "bio": bio[:200],
        "is_private": bool(raw.get("is_private")),
        "enrich_ok": bool(ok),
        "enrich_note": note,
    }


@transaction.atomic
def sync_audience_from_payload(
    account: Account,
    payload: dict,
    *,
    audience_mode: str | None = None,
) -> dict:
    if not isinstance(payload, dict):
        raise ValueError("Некорректный ответ съёма аудитории.")
    if payload.get("error"):
        raise ValueError(str(payload["error"]))

    mode = normalize_audience_mode(
        audience_mode or payload.get("audience_mode") or "full",
    )
    prune_memberships = mode != "enrich"

    wo = str(payload.get("owner_username") or "").strip().lstrip("@").lower()
    wa = str(account.username or "").strip().lstrip("@").lower()
    if wo and wa and wo != wa:
        raise ValueError(
            "Съём вернул список подписчиков для другого профиля (@"
            f"{wo}), а сохранение запрошено для @{wa}. "
            "Закройте лишние вкладки TikTok в окне воркера и повторите съём."
        )

    rows = payload.get("followers")
    if not isinstance(rows, list):
        raise ValueError("В ответе worker нет списка followers.")

    lim = effective_audience_follower_limit()
    rows = rows[:lim]

    platform = account.platform
    kept_member_ids: list[int] = []
    enriched_members: list[dict] = []

    for raw in rows:
        if not isinstance(raw, dict):
            continue
        uname = str(raw.get("username") or "").strip().lstrip("@").lower()[:255]
        if not uname:
            continue
        if raw.get("_reuse_existing"):
            member = AudienceMember.objects.filter(platform=platform, username=uname).first()
            if member:
                _patch_member_from_row_nondestructive(member, raw)
                AccountAudienceMembership.objects.update_or_create(
                    account=account,
                    member=member,
                    defaults={},
                )
                kept_member_ids.append(member.id)
            continue

        if mode == "list":
            ext = str(raw.get("external_id") or "")[:160]
            member, created = AudienceMember.objects.get_or_create(
                platform=platform,
                username=uname,
                defaults={
                    "external_id": ext,
                    "display_name": str(raw.get("display_name") or "")[:255],
                    "avatar_url": str(raw.get("avatar_url") or "")[:2048],
                    "bio": "",
                    "is_private": bool(raw.get("is_private")),
                    "follower_count": 0,
                    "following_count": 0,
                    "like_count": 0,
                },
            )
            if not created:
                _patch_member_from_row_nondestructive(member, raw)
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
            "follower_network": _sanitize_follower_network(raw.get("follower_network")),
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
        if mode == "enrich":
            enriched_members.append(_enrich_member_summary(raw))

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

    if prune_memberships:
        AccountAudienceMembership.objects.filter(account=account).exclude(
            member_id__in=kept_member_ids or [0],
        ).delete()

    account.audience_last_synced_at = timezone.now()
    account.save(update_fields=["audience_last_synced_at", "updated_at"])

    out = {
        "followers_saved": len(kept_member_ids),
        "audience_mode": mode,
        "synced_at": account.audience_last_synced_at.isoformat(),
    }
    if mode == "enrich":
        out["enriched_members"] = enriched_members
        out["enriched_ok_count"] = sum(1 for m in enriched_members if m.get("enrich_ok"))
        out["enriched_weak_count"] = sum(1 for m in enriched_members if not m.get("enrich_ok"))
    return out


def refresh_audience_for_account(
    account: Account,
    *,
    audience_mode: str = "full",
    skip_existing_member_profiles: bool = False,
    enrich_usernames: list[str] | None = None,
) -> dict:
    mode = normalize_audience_mode(audience_mode)
    payload = fetch_audience_payload(
        account,
        audience_mode=mode,
        skip_existing_member_profiles=skip_existing_member_profiles,
        enrich_usernames=enrich_usernames,
    )
    return sync_audience_from_payload(account, payload, audience_mode=mode)


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
