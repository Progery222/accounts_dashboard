import datetime
import re
from pathlib import Path

import httpx

from platforms.worker_pool import call_worker

_HEADERS = {
    "User-Agent": "dashboard-bot/1.0 (by u/mobilefarm_dashboard)",
    "Accept": "application/json,text/plain,*/*",
    "Accept-Language": "en-US,en;q=0.9",
}

_WORKER = Path(__file__).parent / "worker.py"


def _normalize_subreddit(value: str) -> str:
    s = str(value or "").strip()
    s = re.sub(r"^https?://(?:www\.)?reddit\.com/", "", s, flags=re.I)
    s = s.split("?", 1)[0].split("#", 1)[0].strip("/")
    parts = [p for p in s.split("/") if p]
    if parts and parts[0].lower() == "r":
        parts = parts[1:]
    return (parts[0] if parts else s).strip()


def fetch_reddit_subreddit(username: str) -> dict:
    """
    For Reddit platform, Account.username stores subreddit name (without r/).
    Example: username='OpenAI' -> https://www.reddit.com/r/OpenAI/
    """
    subreddit = _normalize_subreddit(username)
    if not subreddit:
        raise ValueError("Укажите subreddit Reddit (например, OpenAI или https://www.reddit.com/r/OpenAI/).")

    about_url = f"https://www.reddit.com/r/{subreddit}/about.json"
    hot_url = f"https://www.reddit.com/r/{subreddit}/hot.json"

    with httpx.Client(headers=_HEADERS, follow_redirects=True, timeout=20.0) as client:
        about_resp = client.get(about_url)
        if about_resp.status_code == 404:
            raise ValueError(f"Reddit r/{subreddit} не найден.")
        if about_resp.status_code >= 400:
            raise ValueError(f"Reddit r/{subreddit}: ошибка {about_resp.status_code} при чтении about.json.")
        about_data = (about_resp.json() or {}).get("data") or {}

        subscribers = int(about_data.get("subscribers") or 0)
        active_users = int(
            about_data.get("active_user_count")
            or about_data.get("accounts_active")
            or 0
        )
        hot_items = []
        # Public listing endpoints are often blocked; still try as a fast path.
        hot_resp = client.get(hot_url, params={"limit": 25, "raw_json": 1})
        if hot_resp.status_code < 400:
            hot_items = ((hot_resp.json() or {}).get("data") or {}).get("children") or []
        if not hot_items:
            try:
                data = call_worker(_WORKER, {"subreddit": subreddit, "limit": 25}, timeout_sec=120.0)
                worker_posts = data.get("posts") if isinstance(data, dict) else []
            except Exception:
                worker_posts = []
            if worker_posts:
                description = about_data.get("public_description") or about_data.get("title") or ""
                if active_users > 0:
                    description = f"{description}\nОнлайн: {active_users}".strip()
                return {
                    "display_name": about_data.get("display_name_prefixed") or f"r/{subreddit}",
                    "avatar_url": (about_data.get("community_icon") or about_data.get("icon_img") or "").split("?", 1)[0],
                    "bio": description,
                    "follower_count": subscribers,
                    "following_count": active_users,
                    "like_count": 0,
                    "post_count": len(worker_posts),
                    "_posts": worker_posts,
                    "username": about_data.get("display_name") or subreddit,
                }

    display_name = about_data.get("display_name_prefixed") or f"r/{subreddit}"
    plain_name = about_data.get("display_name") or subreddit
    avatar_url = (
        about_data.get("community_icon")
        or about_data.get("icon_img")
        or ""
    )
    if avatar_url:
        avatar_url = avatar_url.split("?", 1)[0]

    post_count = 0
    posts = []

    for child in hot_items:
        data = child.get("data") if isinstance(child, dict) else None
        if not isinstance(data, dict):
            continue
        post_count += 1
        score = int(data.get("score") or 0)
        try:
            ratio = float(data.get("upvote_ratio") or 0.0)
        except (TypeError, ValueError):
            ratio = 0.0
        if score > 0 and ratio > 0.55:
            denom = (2.0 * ratio) - 1.0
            est_views = int(round(score / denom)) if denom > 0 else score
        else:
            est_views = score
        created_ts = data.get("created_utc")
        posted_at = None
        if isinstance(created_ts, (int, float)):
            posted_at = datetime.datetime.fromtimestamp(
                created_ts,
                tz=datetime.timezone.utc,
            ).isoformat()
        posts.append({
            "external_id": data.get("id") or "",
            "description": (data.get("title") or "")[:500],
            "thumbnail_url": data.get("thumbnail") if str(data.get("thumbnail", "")).startswith("http") else "",
            "post_url": f"https://www.reddit.com{data.get('permalink', '')}",
            "view_count": max(score, est_views),
            "like_count": score,  # score is treated as likes
            "comment_count": 0,  # intentionally ignored for this app
            "share_count": 0,
            "posted_at": posted_at,
        })

    description = about_data.get("public_description") or about_data.get("title") or ""
    if active_users > 0:
        description = f"{description}\nОнлайн: {active_users}".strip()

    return {
        "display_name": display_name,
        "avatar_url": avatar_url,
        "bio": description,
        # Primary audience metric for subreddit
        "follower_count": subscribers,
        # Online users as "following" proxy (dynamic engagement signal)
        "following_count": active_users,
        "like_count": 0,
        "post_count": post_count,
        "_posts": posts,
        # Keep canonical subreddit name in username field format if scraper discovers variants
        "username": plain_name,
    }
