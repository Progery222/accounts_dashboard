"""
Подписчики для enrich из subs: если в БД dashboard пусто, берём ники из запроса.

AccountsStats по-прежнему использует platforms.audience_skip без изменений.
"""
from __future__ import annotations

from typing import Callable

# Задаётся из subs/tiktok_audience_worker.py до патча audience_skip.
_ORIG_ROWS: Callable[..., list[dict]] | None = None


def subs_existing_audience_member_rows(
    account_id: int,
    *,
    limit: int = 500,
    enrich_usernames: list[str] | None = None,
) -> list[dict]:
    if _ORIG_ROWS is None:
        from platforms.audience_skip import (
            existing_audience_member_rows_for_dashboard_account,
        )

        rows = existing_audience_member_rows_for_dashboard_account(
            account_id, limit=limit,
        )
    else:
        rows = _ORIG_ROWS(account_id, limit=limit)
    if rows:
        return rows
    if not enrich_usernames:
        return []
    out: list[dict] = []
    for raw in enrich_usernames:
        u = str(raw or "").strip().lstrip("@").lower()
        if not u:
            continue
        out.append(
            {
                "username": u,
                "external_id": "",
                "display_name": "",
                "avatar_url": "",
                "bio": "",
                "is_private": False,
                "follower_count": 0,
                "following_count": 0,
                "like_count": 0,
                "profile_language": "",
                "timezone_name": "",
                "follower_network": [],
                "posts": [],
            },
        )
        if limit > 0 and len(out) >= limit:
            break
    return out
