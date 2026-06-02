"""Apify YouTube dataset -> payload как после platforms.youtube.scraper."""
from __future__ import annotations

from typing import Any


def _to_int(v: Any) -> int:
    try:
        return int(v or 0)
    except (TypeError, ValueError):
        return 0


def normalize_youtube(items: list[dict], *, username: str = "") -> dict[str, Any]:
    posts: list[dict[str, Any]] = []
    first_name = ""
    first_subs = 0
    first_avatar = ""

    for row in items:
        ext = str(row.get("id") or row.get("videoId") or "").strip()
        if not ext:
            continue
        if not first_name:
            first_name = str(
                row.get("channelName")
                or row.get("channelTitle")
                or row.get("author")
                or ""
            ).strip()
        if not first_subs:
            first_subs = _to_int(
                row.get("numberOfSubscribers")
                or row.get("subscriberCount")
                or row.get("subscribers")
            )
        if not first_avatar:
            first_avatar = str(
                row.get("channelAvatarUrl")
                or row.get("channelAvatar")
                or row.get("authorAvatar")
                or ""
            ).strip()
        posts.append(
            {
                "external_id": ext,
                "description": str(row.get("title") or row.get("text") or ""),
                "thumbnail_url": str(
                    row.get("thumbnailUrl")
                    or row.get("thumbnail")
                    or row.get("thumbnail_url")
                    or ""
                ),
                "post_url": str(
                    row.get("url") or row.get("videoUrl") or f"https://www.youtube.com/watch?v={ext}"
                ),
                "view_count": _to_int(row.get("viewCount") or row.get("views")),
                "like_count": _to_int(row.get("likes") or row.get("likeCount")),
                "comment_count": _to_int(row.get("commentsCount") or row.get("commentCount")),
                "share_count": 0,
                "posted_at": row.get("date") or row.get("publishedAt"),
            }
        )

    return {
        "display_name": first_name or username.lstrip("@"),
        "avatar_url": first_avatar or None,
        "bio": "",
        "follower_count": first_subs,
        "like_count": 0,
        "post_count": len(posts),
        "_posts": posts,
        "_posts_authoritative": True,
    }
