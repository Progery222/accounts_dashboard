"""CrowdPull profile + playcount → payload как после _scrape Facebook."""
from __future__ import annotations

import datetime
from typing import Any

from django.conf import settings


def _reel_id(url: str) -> str | None:
    u = str(url or "")
    if "/reel/" in u:
        return u.split("/reel/")[-1].strip("/").split("?")[0]
    return None


def _parse_posted_at(raw: Any) -> datetime.datetime | None:
    if raw is None:
        return None
    if isinstance(raw, datetime.datetime):
        return raw if raw.tzinfo else raw.replace(tzinfo=datetime.timezone.utc)
    if isinstance(raw, (int, float)):
        try:
            return datetime.datetime.fromtimestamp(float(raw), tz=datetime.timezone.utc)
        except (ValueError, OSError):
            return None
    s = str(raw).strip()
    if not s:
        return None
    try:
        from django.utils.dateparse import parse_datetime

        dt = parse_datetime(s)
        if dt and dt.tzinfo is None:
            dt = dt.replace(tzinfo=datetime.timezone.utc)
        return dt
    except Exception:
        return None


def normalize_facebook(
    crowd_items: list[dict],
    playcount_items: list[dict] | None,
    *,
    profile_succeeded: bool,
    playcount_succeeded: bool,
    existing_views: dict[str, int] | None = None,
) -> dict[str, Any]:
    existing_views = existing_views or {}
    profile = next((x for x in crowd_items if x.get("type") == "profileInfo"), None)
    raw_posts = [x for x in crowd_items if x.get("postId")]

    views_by_reel: dict[str, int | None] = {}
    views_miss = 0
    for row in playcount_items or []:
        vid = str(row.get("video_id") or _reel_id(row.get("url") or "") or "")
        if not vid:
            continue
        st = str(row.get("status") or "")
        pc = row.get("play_count")
        if st == "ok" and pc is not None:
            views_by_reel[vid] = int(pc)
        else:
            views_miss += 1
            views_by_reel[vid] = None

    posts: list[dict] = []
    partial_views = views_miss > 0 or not playcount_succeeded
    for p in raw_posts:
        post_url = str(p.get("postUrl") or "")
        ext = _reel_id(post_url)
        if not ext:
            ext = str(p.get("postId") or "")
        if not ext:
            continue
        thumb = ""
        imgs = p.get("imageUrls") or []
        vids = p.get("videoUrls") or []
        if imgs:
            thumb = str(imgs[0])
        elif vids:
            thumb = str(vids[0])
        view_count = existing_views.get(ext, 0)
        if ext in views_by_reel and views_by_reel[ext] is not None:
            view_count = views_by_reel[ext]
        posts.append(
            {
                "external_id": ext,
                "description": str(p.get("text") or ""),
                "thumbnail_url": thumb,
                "post_url": post_url,
                "view_count": int(view_count or 0),
                "like_count": int(p.get("reactionCount") or 0),
                "comment_count": int(p.get("commentCount") or 0),
                "share_count": int(p.get("shareCount") or 0),
                "posted_at": _parse_posted_at(p.get("timestamp")),
            }
        )

    display_name = str((profile or {}).get("name") or "")
    follower_count = int((profile or {}).get("followersCount") or 0)
    max_posts = int(getattr(settings, "FACEBOOK_MAX_POSTS", 80) or 80)
    partial_posts = len(posts) < max(1, int(max_posts * 0.5)) and len(raw_posts) > 0

    result: dict[str, Any] = {
        "display_name": display_name,
        "avatar_url": None,
        "bio": str((profile or {}).get("bio") or ""),
        "follower_count": follower_count,
        "like_count": 0,
        "post_count": len(posts),
        "_posts": posts,
        "_posts_authoritative": profile_succeeded and playcount_succeeded,
    }
    if partial_views or partial_posts or not playcount_succeeded:
        result["_partial"] = True
    if profile_succeeded and not playcount_succeeded and posts:
        result["_posts_authoritative"] = True
    return result
