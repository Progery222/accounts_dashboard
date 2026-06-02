"""Apify Reddit dataset -> payload как после platforms.reddit.scraper."""
from __future__ import annotations

from typing import Any


def _to_int(v: Any) -> int:
    try:
        return int(v or 0)
    except (TypeError, ValueError):
        return 0


def normalize_reddit(items: list[dict], *, username: str = "") -> dict[str, Any]:
    posts: list[dict[str, Any]] = []
    display_name = f"r/{username}"
    avatar_url = ""
    bio = ""
    followers = 0

    for row in items:
        # community row (some actors emit one metadata row)
        if not row.get("id") and (row.get("subreddit") or row.get("community")):
            display_name = str(
                row.get("display_name_prefixed")
                or row.get("subreddit")
                or row.get("community")
                or display_name
            )
            followers = max(
                followers,
                _to_int(row.get("subscribers") or row.get("communitySubscribers")),
            )
            avatar_url = str(row.get("icon") or row.get("avatarUrl") or avatar_url)
            bio = str(row.get("description") or bio)
            continue

        ext = str(row.get("id") or "").strip()
        if not ext:
            continue
        title = str(row.get("title") or "")
        permalink = str(row.get("permalink") or row.get("url") or "")
        if permalink and permalink.startswith("/"):
            permalink = f"https://www.reddit.com{permalink}"
        score = _to_int(
            row.get("score")
            or row.get("upVotes")
            or row.get("upvotes")
            or row.get("ups")
        )
        comments = _to_int(row.get("numComments") or row.get("commentsCount") or row.get("comments"))
        posts.append(
            {
                "external_id": ext,
                "description": title,
                "thumbnail_url": str(row.get("thumbnail") or row.get("thumbnailUrl") or ""),
                "post_url": permalink,
                "view_count": max(score, 0),
                "like_count": max(score, 0),
                "comment_count": max(comments, 0),
                "share_count": 0,
                "posted_at": row.get("createdAt") or row.get("created_utc"),
            }
        )

    if posts and not display_name:
        sub = str(items[0].get("subreddit") or username).strip()
        display_name = f"r/{sub}" if not sub.lower().startswith("r/") else sub

    return {
        "display_name": display_name,
        "avatar_url": avatar_url or None,
        "bio": bio,
        "follower_count": followers,
        "like_count": 0,
        "post_count": len(posts),
        "_posts": posts,
        "_posts_authoritative": True,
    }
