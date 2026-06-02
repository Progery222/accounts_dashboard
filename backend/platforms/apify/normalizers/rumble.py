"""Apify Rumble dataset -> payload как после platforms.rumble.scraper."""
from __future__ import annotations

from typing import Any


def _to_int(v: Any) -> int:
    try:
        return int(v or 0)
    except (TypeError, ValueError):
        return 0


def normalize_rumble(items: list[dict], *, username: str = "") -> dict[str, Any]:
    posts: list[dict[str, Any]] = []
    display_name = username
    avatar_url = ""
    bio = ""
    followers = 0
    channel_views = 0

    for row in items:
        # channel/profile rows
        if row.get("channelName") or row.get("channelUrl"):
            display_name = str(row.get("channelName") or display_name or username)
            avatar_url = str(row.get("channelAvatarUrl") or row.get("channelAvatar") or avatar_url)
            bio = str(row.get("channelDescription") or bio)
            followers = max(
                followers,
                _to_int(row.get("followersCount") or row.get("followerCount") or row.get("subscribers")),
            )
            channel_views = max(
                channel_views,
                _to_int(row.get("channelViews") or row.get("viewsTotal")),
            )

        ext = str(row.get("id") or row.get("videoId") or "").strip()
        post_url = str(row.get("url") or row.get("videoUrl") or "")
        if not ext and post_url:
            ext = post_url.rstrip("/").split("/")[-1].split("-", 1)[0]
        if not ext:
            continue

        posts.append(
            {
                "external_id": ext,
                "description": str(row.get("title") or row.get("text") or ""),
                "thumbnail_url": str(row.get("thumbnailUrl") or row.get("thumbnail") or ""),
                "post_url": post_url,
                "view_count": _to_int(row.get("viewCount") or row.get("views")),
                "like_count": _to_int(row.get("likes") or row.get("likeCount")),
                "comment_count": _to_int(row.get("commentsCount") or row.get("commentCount")),
                "share_count": 0,
                "posted_at": row.get("publishedAt") or row.get("date"),
            }
        )

    return {
        "display_name": display_name or username,
        "avatar_url": avatar_url or None,
        "bio": bio,
        "follower_count": followers,
        "view_count": channel_views,
        "like_count": 0,
        "post_count": len(posts),
        "_posts": posts,
        "_posts_authoritative": True,
    }
