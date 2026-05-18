"""Доступ к БД дашборда из worker-процессов (Django ORM после setup)."""

from __future__ import annotations


def existing_audience_usernames_for_dashboard_account(account_id: int) -> set[str]:
    """Нормализованные ники подписчиков, уже связанных с аккаунтом `accounts.Account`."""
    import os

    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    import django

    django.setup()
    from accounts.models import AudienceMember

    return {
        str(u or "").strip().lstrip("@").lower()
        for u in AudienceMember.objects.filter(memberships__account_id=account_id).values_list(
            "username",
            flat=True,
        )
    }


def existing_audience_member_rows_for_dashboard_account(
    account_id: int,
    *,
    limit: int = 500,
) -> list[dict]:
    """Строки подписчиков из БД для режима enrich (без повторного съёма списка)."""
    import os

    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    import django

    django.setup()
    from accounts.models import AudienceMember

    qs = AudienceMember.objects.filter(memberships__account_id=int(account_id)).order_by("username")
    if limit > 0:
        qs = qs[: max(1, int(limit))]
    rows: list[dict] = []
    for m in qs:
        rows.append(
            {
                "username": str(m.username or "").strip().lstrip("@").lower(),
                "external_id": str(m.external_id or "")[:160],
                "display_name": str(m.display_name or "")[:255],
                "avatar_url": str(m.avatar_url or "")[:2048],
                "bio": str(m.bio or "")[:4000],
                "is_private": bool(m.is_private),
                "follower_count": int(m.follower_count or 0),
                "following_count": int(m.following_count or 0),
                "like_count": int(m.like_count or 0),
                "profile_language": str(m.profile_language or "")[:32],
                "timezone_name": str(m.timezone_name or "")[:64],
                "follower_network": m.follower_network if isinstance(m.follower_network, list) else [],
                "posts": [],
            },
        )
    return rows


def filter_audience_followers_by_usernames(
    followers: list[dict],
    usernames: list[str] | None,
) -> list[dict]:
    """Оставить только указанные ники (для точечного enrich)."""
    if not usernames:
        return followers
    want = {str(u or "").strip().lstrip("@").lower() for u in usernames if str(u or "").strip()}
    if not want:
        return followers
    out: list[dict] = []
    for row in followers:
        un = str(row.get("username") or "").strip().lstrip("@").lower()
        if un and un in want:
            out.append(row)
    return out
