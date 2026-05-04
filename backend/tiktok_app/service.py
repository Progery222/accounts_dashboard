import json
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx
from platforms.worker_pool import call_worker

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Cache-Control": "max-age=0",
}

_UNIVERSAL_RE = re.compile(
    r'<script id="__UNIVERSAL_DATA_FOR_REHYDRATION__"[^>]*>(.*?)</script>',
    re.DOTALL,
)

_WORKER = Path(__file__).parent / "playwright_worker.py"

_executor = ThreadPoolExecutor(max_workers=2)


def _parse_videos(items: list[dict]) -> list[dict]:
    videos = []
    for item in items:
        stats = item.get("stats", {})
        videos.append({
            "id": str(item.get("id", "")),
            "description": item.get("desc", ""),
            "cover": item.get("video", {}).get("cover", ""),
            "play_count": stats.get("playCount", 0),
            "like_count": stats.get("diggCount", 0),
            "comment_count": stats.get("commentCount", 0),
            "share_count": stats.get("shareCount", 0),
            "created_at": item.get("createTime", 0),
        })
    return videos


def _run_worker(url: str) -> list[dict]:
    # Read browser settings from Django settings so the subprocess
    # always gets the correct values even if os.environ wasn't updated.
    try:
        from django.conf import settings as _s
        browser_env = {
            "BROWSER_HEADLESS":    str(_s.BROWSER_HEADLESS).lower(),
            "BROWSER_STATE_FILE":  _s.BROWSER_STATE_FILE or "",
            "BROWSER_PROFILE_DIR": _s.BROWSER_PROFILE_DIR or "",
        }
    except Exception:
        browser_env = {}

    os.environ.update(browser_env)
    try:
        return call_worker(_WORKER, {"url": url})
    except Exception as e:
        print(f"[worker] error: {e}", file=sys.stderr)
        return []


def fetch_tiktok_profile(username: str) -> dict:
    """Synchronous — safe to call from Django views."""
    url = f"https://www.tiktok.com/@{username}"

    # TikTok's SSR occasionally returns a blank/error page on the first request.
    # Retry up to 3 times (same as clicking "Refresh" in the browser).
    html = ""
    last_status = 0
    with httpx.Client(headers=_HEADERS, follow_redirects=True, timeout=30.0) as client:
        for _attempt in range(3):
            response = client.get(url)
            last_status = response.status_code
            if last_status == 404:
                raise ValueError(f"Профиль @{username} не найден.")
            if last_status != 200:
                if _attempt < 2:
                    import time; time.sleep(1.5)
                    continue
                response.raise_for_status()
            html = response.text
            # Detect error page ("Something went wrong" / empty shell without data)
            if _UNIVERSAL_RE.search(html):
                break   # good page, stop retrying
            if _attempt < 2:
                print(
                    f"[tiktok] SSR error page on attempt {_attempt + 1}, retrying…",
                    file=sys.stderr,
                )
                import time; time.sleep(1.5)
            # else: fall through with whatever we have

    match = _UNIVERSAL_RE.search(html)
    if not match:
        raise ValueError(
            f"Не удалось получить данные @{username}. "
            "Профиль может быть приватным или TikTok заблокировал запрос."
        )

    scope = json.loads(match.group(1)).get("__DEFAULT_SCOPE__", {})
    user_info = scope.get("webapp.user-detail", {}).get("userInfo", {})
    user = user_info.get("user", {})
    stats = user_info.get("stats", {})

    if not user:
        raise ValueError(f"Профиль @{username} не найден.")

    # Use videos already embedded in the HTML (server-side rendered).
    # Playwright is only invoked when the HTML has no video list — avoids
    # opening a browser window on every refresh in local-dev mode.
    videos: list[dict] = []

    # TikTok periodically renames the scope key — search all known variants
    # and fall back to scanning every scope value for an itemList array.
    raw: list[dict] = []
    for key in ("webapp.video-list", "webapp.videofeed", "webapp.feed"):
        candidate = scope.get(key, {})
        if isinstance(candidate, dict):
            items_candidate = candidate.get("itemList") or candidate.get("videoList") or []
            if items_candidate:
                print(f"[tiktok] found video list in scope[{key!r}] ({len(items_candidate)} items)")
                raw = items_candidate
                break

    # Generic fallback: walk all scope values looking for any list whose first
    # element looks like a TikTok video item (has "id" and "stats" keys).
    if not raw:
        for key, val in scope.items():
            if not isinstance(val, dict):
                continue
            for subkey, subval in val.items():
                if (
                    isinstance(subval, list) and subval
                    and isinstance(subval[0], dict)
                    and "id" in subval[0] and "stats" in subval[0]
                ):
                    print(f"[tiktok] found video list via fallback scan scope[{key!r}][{subkey!r}] ({len(subval)} items)")
                    raw = subval
                    break
            if raw:
                break

    if not raw:
        print(f"[tiktok] no video list in HTML for @{username}; scope keys: {list(scope.keys())}")

    if raw:
        videos = _parse_videos(raw)

    if not videos:
        items = _run_worker(url)
        videos = _parse_videos(items)

    return {
        "username": user.get("uniqueId", username),
        "nickname": user.get("nickname", ""),
        "avatar": user.get("avatarMedium") or user.get("avatarLarger", ""),
        "bio": user.get("signature", ""),
        "verified": user.get("verified", False),
        "follower_count": stats.get("followerCount", 0),
        "following_count": stats.get("followingCount", 0),
        "like_count": stats.get("heartCount") or stats.get("heart", 0),
        "video_count": stats.get("videoCount", 0),
        "videos": videos,
    }
