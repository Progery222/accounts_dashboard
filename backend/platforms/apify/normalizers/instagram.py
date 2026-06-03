"""instagram-profile-scraper + instagram-scraper → payload как worker/scraper IG."""
from __future__ import annotations

import datetime
import re
from typing import Any


def _parse_posted_at(raw: Any) -> datetime.datetime | None:
    if raw is None:
        return None
    if isinstance(raw, datetime.datetime):
        return raw if raw.tzinfo else raw.replace(tzinfo=datetime.timezone.utc)
    if isinstance(raw, (int, float)):
        try:
            ts = float(raw)
            if ts > 1e12:
                ts /= 1000.0
            return datetime.datetime.fromtimestamp(ts, tz=datetime.timezone.utc)
        except (ValueError, OSError):
            return None
    return None


def _clean_display_name(full_name: str, username: str) -> str:
    s = str(full_name or "").strip()
    uname = (username or "").lstrip("@").strip()
    if uname:
        suffix = f" (@{uname})"
        if s.endswith(suffix):
            s = s[: -len(suffix)].strip()
    return s


def normalize_instagram(
    profile_items: list[dict],
    post_items: list[dict],
    *,
    profile_succeeded: bool,
    posts_succeeded: bool,
    existing_likes: dict[str, int] | None = None,
) -> dict[str, Any]:
    existing_likes = existing_likes or {}
    profile = profile_items[0] if profile_items else {}
    username = str(profile.get("username") or "").lstrip("@")
    posts_count = int(profile.get("postsCount") or 0)

    posts: list[dict] = []
    for row in post_items:
        code = row.get("shortCode") or row.get("shortcode")
        if not code:
            continue
        ext = str(code)
        vv = int(row.get("videoViewCount") or 0)
        vp = int(row.get("videoPlayCount") or 0)
        view_count = max(vv, vp)
        like_count = int(row.get("likesCount") or 0)
        prev_like = int(existing_likes.get(ext, 0) or 0)
        if prev_like > like_count:
            like_count = prev_like
        posts.append(
            {
                "external_id": ext,
                "description": str(row.get("caption") or ""),
                "thumbnail_url": str(row.get("displayUrl") or ""),
                "post_url": str(row.get("url") or f"https://www.instagram.com/p/{ext}/"),
                "view_count": view_count,
                "like_count": like_count,
                "comment_count": int(row.get("commentsCount") or 0),
                "share_count": 0,
                "posted_at": _parse_posted_at(row.get("timestamp")),
            }
        )

    partial = bool(posts_count and len(posts) < posts_count * 0.8)
    avatar = profile.get("profilePicUrlHD") or profile.get("profilePicUrl") or None
    avatar = str(avatar).strip() if avatar else ""
    out: dict[str, Any] = {
        "display_name": _clean_display_name(str(profile.get("fullName") or ""), username),
        "bio": str(profile.get("biography") or ""),
        "follower_count": int(profile.get("followersCount") or 0),
        "like_count": 0,
        "post_count": posts_count or len(posts),
        "_posts": posts,
        "_posts_authoritative": profile_succeeded and posts_succeeded,
    }
    if avatar:
        out["avatar_url"] = avatar
    if partial or not posts_succeeded:
        out["_partial"] = True
    return out
