"""Clockworks tiktok-profile-scraper → payload как после _scrape TikTok."""
from __future__ import annotations

import datetime
from typing import Any


def normalize_tiktok(items: list[dict], *, run_succeeded: bool = True) -> dict[str, Any]:
    if not items:
        if run_succeeded:
            return {
                "display_name": "",
                "avatar_url": None,
                "bio": "",
                "follower_count": 0,
                "like_count": 0,
                "post_count": 0,
                "_posts": [],
                "_posts_authoritative": True,
            }
        raise ValueError("Пустой dataset TikTok Apify")

    author = items[0].get("authorMeta") or {}
    posts: list[dict] = []
    for row in items:
        vid = row.get("id") or row.get("videoId")
        if vid is None:
            continue
        meta = row.get("videoMeta") or {}
        web_url = row.get("webVideoUrl") or ""
        username = (author.get("name") or author.get("uniqueId") or "").strip()
        if not web_url and username:
            web_url = f"https://www.tiktok.com/@{username}/video/{vid}"
        created = row.get("createTime")
        posted_at = None
        if created is not None:
            try:
                posted_at = datetime.datetime.fromtimestamp(int(created), tz=datetime.timezone.utc)
            except (TypeError, ValueError, OSError):
                posted_at = None
        posts.append(
            {
                "external_id": str(vid),
                "description": str(row.get("text") or ""),
                "thumbnail_url": str(meta.get("coverUrl") or meta.get("cover") or ""),
                "post_url": web_url,
                "view_count": int(row.get("playCount") or 0),
                "like_count": int(row.get("diggCount") or 0),
                "comment_count": int(row.get("commentCount") or 0),
                "share_count": int(row.get("shareCount") or 0),
                "posted_at": posted_at,
            }
        )

    expected = int(author.get("video") or 0)
    partial = bool(expected and len(posts) < max(1, expected * 0.5))
    profile_likes = int(author.get("heart") or author.get("heartCount") or 0)
    posts_likes_sum = sum(p["like_count"] for p in posts)
    # Clockworks иногда отдаёт heart на 1 ниже суммы diggCount и UI TikTok (см. @yllazenlive).
    like_count = max(profile_likes, posts_likes_sum) if posts else profile_likes
    return {
        "display_name": str(author.get("nickName") or author.get("nickname") or ""),
        "avatar_url": author.get("avatar") or author.get("avatarMedium") or None,
        "bio": str(author.get("signature") or ""),
        "follower_count": int(author.get("fans") or author.get("followerCount") or 0),
        "like_count": like_count,
        "post_count": int(author.get("video") or len(posts)),
        "_posts": posts,
        "_posts_authoritative": run_succeeded,
        **({"_partial": True} if partial else {}),
    }
