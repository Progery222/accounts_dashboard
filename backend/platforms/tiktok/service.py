import json
import html as _html
import os
import re
import sys
import time
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

_WORKER = Path(__file__).parent / "worker.py"

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


def _extract_username_from_url(url: str) -> str:
    m = re.search(r"/@([^/?#]+)", url)
    return m.group(1).strip().lower() if m else ""


def _parse_short_count(text: str) -> int:
    if not text:
        return 0
    t = str(text).replace("\xa0", "").replace("\u202f", "").strip()
    t = t.replace(",", "")
    m = re.match(r"^([\d]+(?:\.[\d]+)?)\s*([KMB]?)$", t, flags=re.I)
    if not m:
        digits = re.sub(r"[^\d]", "", t)
        return int(digits) if digits else 0
    num = float(m.group(1))
    suffix = m.group(2).upper()
    mult = {"": 1, "K": 1_000, "M": 1_000_000, "B": 1_000_000_000}[suffix]
    return int(num * mult)


def _extract_tiktok_stats_from_html(html: str) -> dict:
    """
    Fallback parser for profile stats from meta tags/plain HTML.
    Useful when SSR JSON lacks `stats`.
    """
    raw_html = html or ""
    unescaped = _html.unescape(raw_html)
    # Most reliable source on public pages: meta description content.
    md = re.search(r'<meta\s+name="description"\s+content="([^"]+)"', unescaped, flags=re.I)
    text = md.group(1) if md else unescaped
    fm = re.search(r"([\d.,]+[KMB]?)\s+Followers?", text, flags=re.I)
    folm = re.search(r"([\d.,]+[KMB]?)\s+Following", text, flags=re.I)
    lm = re.search(r"([\d.,]+[KMB]?)\s+Likes?", text, flags=re.I)
    follower_count = _parse_short_count(fm.group(1)) if fm else 0
    following_count = _parse_short_count(folm.group(1)) if folm else 0
    like_count = _parse_short_count(lm.group(1)) if lm else 0

    # JSON fallback: some TikTok pages hide counts from meta tags but still embed
    # numeric stats in inline JSON blocks.
    if follower_count == 0:
        m = re.search(r'"followerCount"\s*:\s*(\d+)', raw_html)
        if m:
            follower_count = int(m.group(1))
    if following_count == 0:
        m = re.search(r'"followingCount"\s*:\s*(\d+)', raw_html)
        if m:
            following_count = int(m.group(1))
    if like_count == 0:
        m = re.search(r'"heartCount"\s*:\s*(\d+)', raw_html) or re.search(r'"heart"\s*:\s*(\d+)', raw_html)
        if m:
            like_count = int(m.group(1))

    return {
        "follower_count": follower_count,
        "following_count": following_count,
        "like_count": like_count,
    }


def _extract_avatar_from_html(html: str) -> str:
    raw_html = html or ""
    m = re.search(r'<meta\s+property="og:image"\s+content="([^"]+)"', raw_html, flags=re.I)
    if not m:
        return ""
    return _html.unescape(m.group(1)).strip()


def _filter_profile_items(items: list[dict], expected_username: str, expected_user_id: str = "") -> list[dict]:
    expected_username = (expected_username or "").strip().lstrip("@").lower()
    expected_user_id = (expected_user_id or "").strip()
    if not expected_username and not expected_user_id:
        return items
    filtered: list[dict] = []
    for item in items:
        author = item.get("author", {}) if isinstance(item, dict) else {}
        author_username = str(author.get("uniqueId") or "").strip().lower()
        author_id = str(author.get("id") or "").strip()
        if expected_username and author_username and author_username == expected_username:
            filtered.append(item)
            continue
        if expected_user_id and author_id and author_id == expected_user_id:
            filtered.append(item)
            continue
    return filtered


def _run_worker(url: str) -> tuple[list[dict], dict]:
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

    if not _WORKER.exists():
        print(
            f"[tiktok_service] ERROR: worker not found at {_WORKER}",
            file=sys.stderr,
        )
        return [], {}

    os.environ.update(browser_env)
    try:
        data = call_worker(_WORKER, {"url": url})
        if isinstance(data, list):
            # Backward compatibility with old worker payload.
            return _filter_profile_items(data, _extract_username_from_url(url)), {}
        items = data.get("items") or []
        profile_stats = data.get("profile_stats") or {}
        return _filter_profile_items(items, _extract_username_from_url(url)), profile_stats
    except Exception as e:
        print(f"[worker] error: {e}", file=sys.stderr)
        return [], {}


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
                # TikTok often returns 403/anti-bot HTML for plain HTTP requests.
                # Don't hard-fail here: we want to continue to the Playwright fallback.
                if _attempt < 2:
                    time.sleep(1.5)
                    continue
                print(
                    f"[tiktok] HTTP {last_status} for @{username}; falling back to worker",
                    file=sys.stderr,
                )
                html = response.text
                break
            html = response.text
            # Detect error page ("Something went wrong" / empty shell without data)
            if _UNIVERSAL_RE.search(html):
                break   # good page, stop retrying
            if _attempt < 2:
                print(
                    f"[tiktok] SSR error page on attempt {_attempt + 1}, retrying…",
                    file=sys.stderr,
                )
                time.sleep(1.5)
            # else: fall through with whatever we have

    match = _UNIVERSAL_RE.search(html)
    if match:
        scope = json.loads(match.group(1)).get("__DEFAULT_SCOPE__", {})
        user_info = scope.get("webapp.user-detail", {}).get("userInfo", {})
        user = user_info.get("user", {})
        stats = user_info.get("stats", {})
    else:
        # Don't fail hard here: TikTok often omits SSR data under bot pressure.
        # We still try the Playwright worker and return partial data if needed.
        print(
            f"[tiktok] no __UNIVERSAL_DATA_FOR_REHYDRATION__ for @{username}; "
            "falling back to worker",
            file=sys.stderr,
        )
        scope = {}
        user = {}
        stats = {}

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
        raw = _filter_profile_items(raw, username, str(user.get("id") or ""))
        videos = _parse_videos(raw)

    worker_stats = {}
    if not videos:
        items, worker_stats = _run_worker(url)
        videos = _parse_videos(items)

    html_stats = _extract_tiktok_stats_from_html(html)
    follower_count = stats.get("followerCount", 0) or html_stats["follower_count"]
    following_count = stats.get("followingCount", 0) or html_stats["following_count"]
    like_count = (stats.get("heartCount") or stats.get("heart", 0)) or html_stats["like_count"]

    # If core counters are still empty, ask Playwright worker for DOM-derived stats
    # (XPath/CSS selectors on rendered profile header).
    if (follower_count == 0 or like_count == 0) and not worker_stats:
        _, worker_stats = _run_worker(url)

    worker_follower = _parse_short_count(worker_stats.get("follower_text", "")) if worker_stats else 0
    worker_following = _parse_short_count(worker_stats.get("following_text", "")) if worker_stats else 0
    worker_likes = _parse_short_count(worker_stats.get("like_text", "")) if worker_stats else 0

    if follower_count == 0:
        follower_count = worker_follower
    if following_count == 0:
        following_count = worker_following
    if like_count == 0:
        like_count = worker_likes
    if like_count == 0 and videos:
        # Fallback when TikTok hides profile "Likes" counter in DOM for this session.
        like_count = sum(int(v.get("like_count", 0) or 0) for v in videos)
    video_count = stats.get("videoCount", 0)
    avatar_url = (
        user.get("avatarMedium")
        or user.get("avatarLarger", "")
        or (worker_stats.get("avatar_url") if worker_stats else "")
        or _extract_avatar_from_html(html)
        or (videos[0].get("cover", "") if videos else "")
    )

    # For TikTok, empty video list is often a transient anti-bot/API issue.
    # Never treat an empty list as authoritative: keep already saved posts.
    posts_authoritative = bool(videos)

    result = {
        "username": user.get("uniqueId", username),
        "nickname": user.get("nickname", ""),
        "avatar": avatar_url,
        "bio": user.get("signature", ""),
        "verified": user.get("verified", False),
        "follower_count": follower_count,
        "following_count": following_count,
        "like_count": like_count,
        "video_count": video_count,
        "videos": videos,
        "_posts_authoritative": posts_authoritative,
    }
    # Mark partial only when core stats are still unavailable.
    if not user and follower_count == 0 and like_count == 0 and video_count == 0:
        result["_partial"] = True
    return result
