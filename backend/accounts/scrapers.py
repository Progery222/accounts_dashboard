import asyncio
import json
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import httpx

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

_INSTAGRAM_WORKER = Path(__file__).parent / "instagram_worker.py"
_TELEGRAM_WORKER  = Path(__file__).parent / "telegram_worker.py"
_X_WORKER         = Path(__file__).parent / "x_worker.py"
_THREADS_WORKER   = Path(__file__).parent / "threads_worker.py"


def _parse_count(text: str) -> int:
    if not text:
        return 0
    text = re.split(r'\s+(?:subscriber|member|follower|video|post|подписч)', text, flags=re.I)[0].strip()
    m = re.match(r'^([\d]+(?:[.,][\d]+)?)\s*([KMBT])', text.replace(' ', '').upper())
    if m:
        try:
            num = float(m.group(1).replace(',', '.'))
            return int(num * {'K': 1_000, 'M': 1_000_000, 'B': 1_000_000_000, 'T': 1_000_000_000_000}[m.group(2)])
        except (ValueError, KeyError):
            pass
    digits = re.sub(r'[^\d]', '', text)
    return int(digits) if digits else 0


# ─── Telegram ────────────────────────────────────────────────────────────────

def fetch_telegram_profile(username: str) -> dict:
    """
    Fetch Telegram channel data.

    Strategy:
    1. Telethon MTProto — when TELEGRAM_API_ID/HASH + session file are configured.
       Returns complete data, skips everything else.
    2. Hybrid httpx + Playwright:
       - httpx scrapes t.me for avatar, bio, and posts with *real* message IDs.
       - Playwright subprocess scrapes web.telegram.org for the accurate subscriber count
         (httpx sometimes misses it when the channel hides web previews).
       - Results are merged: httpx posts/avatar + Playwright subscriber count.
    """
    username = username.lstrip("@")
    try:
        from django.conf import settings
        api_id = getattr(settings, "TELEGRAM_API_ID", None)
        api_hash = getattr(settings, "TELEGRAM_API_HASH", None)
        session_file = getattr(settings, "TELEGRAM_SESSION_FILE", "")
    except Exception:
        api_id = api_hash = session_file = None

    # ── 1. Telethon ───────────────────────────────────────────────────────────
    if api_id and api_hash and session_file and Path(session_file).with_suffix(".session").exists():
        try:
            return _fetch_telegram_telethon(username, int(api_id), api_hash, session_file)
        except Exception as e:
            print(f"[telegram] Telethon error for @{username}: {e}", file=sys.stderr)

    # ── 2a. httpx — base data: avatar, bio, posts with real sequential IDs ────
    httpx_data = None
    try:
        httpx_data = _fetch_telegram_httpx(username)
    except ValueError:
        raise  # channel not found
    except Exception as e:
        print(f"[telegram] httpx error for @{username}: {e}", file=sys.stderr)

    # ── 2b. Playwright — accurate subscriber count ────────────────────────────
    pw_data = None
    try:
        pw_data = _fetch_telegram_playwright(username)
    except ValueError as e:
        # Auth required or channel not found in web.telegram.org
        if httpx_data is None:
            raise  # both scrapers failed — surface the error
        print(f"[telegram] Playwright skipped for @{username}: {e}", file=sys.stderr)
    except Exception as e:
        print(f"[telegram] Playwright error for @{username}: {e}", file=sys.stderr)

    if httpx_data is None and pw_data is None:
        raise ValueError(f"Telegram @{username}: не удалось получить данные")

    # ── Merge ─────────────────────────────────────────────────────────────────
    # httpx provides: avatar CDN URL, bio, posts with real sequential IDs.
    # Playwright provides: accurate follower_count, posts with view counts +
    #   reactions (for channels where t.me/s/ is disabled or returns nothing).
    base = httpx_data or {
        "display_name": "", "avatar_url": "", "bio": "",
        "follower_count": 0, "following_count": 0,
        "like_count": 0, "post_count": 0, "_posts": [],
    }

    if pw_data:
        # Always prefer Playwright's subscriber count (more reliable than httpx).
        if pw_data.get("follower_count"):
            base["follower_count"] = pw_data["follower_count"]

        # Use Playwright's display_name if httpx didn't get one.
        if pw_data.get("display_name") and not base.get("display_name"):
            base["display_name"] = pw_data["display_name"]

        # If httpx returned no posts (channel has web preview disabled) but
        # Playwright managed to extract messages, use those instead.
        if not base.get("_posts") and pw_data.get("_posts"):
            base["_posts"] = pw_data["_posts"]

        # post_count: prefer the larger of the two estimates.
        # httpx uses max(message_id) from t.me/s/ stream; Playwright uses
        # max(real_id) decoded from data-mid attributes.  Take whichever is bigger.
        pw_pc = pw_data.get("post_count")
        base_pc = base.get("post_count") or 0
        if pw_pc and pw_pc > base_pc:
            base["post_count"] = pw_pc

    return base


def _fetch_telegram_playwright(username: str) -> dict:
    """Get subscriber count via web.telegram.org/k/ Playwright subprocess."""
    return _run_worker(_TELEGRAM_WORKER, json.dumps({"username": username}), f"Telegram @{username}")


def _fetch_telegram_telethon(username: str, api_id: int, api_hash: str, session_file: str) -> dict:
    """Fetch via Telethon MTProto — full post data, works without web view."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(
            _fetch_telegram_telethon_async(username, api_id, api_hash, session_file)
        )
    finally:
        loop.close()


async def _fetch_telegram_telethon_async(username: str, api_id: int, api_hash: str, session_file: str) -> dict:
    from telethon import TelegramClient
    from telethon.tl.functions.channels import GetFullChannelRequest

    async with TelegramClient(session_file, api_id, api_hash) as client:
        try:
            entity = await client.get_entity(username)
        except Exception as e:
            raise ValueError(f"Telegram @{username} не найден: {e}")

        display_name = getattr(entity, "title", username)
        follower_count = getattr(entity, "participants_count", 0) or 0

        # Try to get full info: bio, exact subscriber count
        bio = ""
        avatar_url = ""
        try:
            full = await client(GetFullChannelRequest(entity))
            bio = full.full_chat.about or ""
            follower_count = full.full_chat.participants_count or follower_count
        except Exception:
            pass

        # Fetch last 50 posts
        posts = []
        max_id = 0
        async for msg in client.iter_messages(entity, limit=50):
            if not msg.id:
                continue
            if msg.id > max_id:
                max_id = msg.id

            # Sum all reactions as like_count
            like_count = 0
            if msg.reactions:
                for r in msg.reactions.results:
                    like_count += r.count

            posts.append({
                "external_id": str(msg.id),
                "description": (msg.text or msg.message or "")[:500],
                "thumbnail_url": "",
                "post_url": f"https://t.me/{username}/{msg.id}",
                "view_count": msg.views or 0,
                "like_count": like_count,
                "comment_count": msg.replies.replies if msg.replies else 0,
                "share_count": msg.forwards or 0,
                "posted_at": msg.date.isoformat() if msg.date else None,
            })

    return {
        "display_name": display_name,
        "avatar_url": avatar_url,
        "bio": bio,
        "follower_count": follower_count,
        "following_count": 0,
        "like_count": 0,  # aggregated from posts in _apply_refresh
        "post_count": max_id,
        "_posts": posts,
    }


def _parse_tg_views(text: str) -> int:
    if not text:
        return 0
    text = text.strip().replace("\xa0", "").replace(" ", "")
    m = re.match(r"^([\d]+(?:[.,][\d]+)?)\s*([KkMmBb]?)$", text)
    if not m:
        return 0
    num = float(m.group(1).replace(",", "."))
    suffix = m.group(2).upper()
    return int(num * {"K": 1_000, "M": 1_000_000, "B": 1_000_000_000}.get(suffix, 1))


def _fetch_telegram_httpx(username: str) -> dict:
    """Fallback: scrape t.me public page + stream (works only when web preview is on)."""
    url = f"https://t.me/{username}"
    with httpx.Client(headers=_HEADERS, follow_redirects=True, timeout=15.0) as client:
        r = client.get(url)
        if r.status_code == 404:
            raise ValueError(f"Telegram @{username} не найден")
        r.raise_for_status()
        html = r.text

        post_count, posts = _fetch_telegram_stream(username, client)

    name_m = re.search(r'<div class="tgme_page_title"[^>]*>\s*<span[^>]*>([^<]+)</span>', html)
    display_name = name_m.group(1).strip() if name_m else username

    extra_m = re.search(r'<div class="tgme_page_extra">([^<]+)</div>', html)
    follower_count = _parse_count(extra_m.group(1).strip()) if extra_m else 0

    desc_m = re.search(r'<div class="tgme_page_description"[^>]*>(.*?)</div>', html, re.DOTALL)
    bio = re.sub(r"<[^>]+>", "", desc_m.group(1)).strip() if desc_m else ""

    avatar_m = re.search(r'<img class="tgme_page_photo_image"[^>]+src="([^"]+)"', html)
    avatar_url = avatar_m.group(1) if avatar_m else ""

    return {
        "display_name": display_name,
        "avatar_url": avatar_url,
        "bio": bio,
        "follower_count": follower_count,
        "following_count": 0,
        "like_count": 0,
        "post_count": post_count,
        "_posts": posts,
    }


def _fetch_telegram_stream(username: str, client: httpx.Client) -> tuple[int, list]:
    url = f"https://t.me/s/{username}"
    try:
        r = client.get(url, timeout=10.0)
        if r.status_code != 200:
            return 0, []
        html = r.text
    except Exception:
        return 0, []

    posts = []
    for msg_m in re.finditer(
        r'<div[^>]+class="[^"]*tgme_widget_message[^"]*"[^>]+data-post="[^/]+/(\d+)"(.*?)'
        r"</div>\s*</div>\s*</div>",
        html, re.DOTALL,
    ):
        msg_id = msg_m.group(1)
        block = msg_m.group(2)
        text_m = re.search(
            r'<div[^>]+class="[^"]*tgme_widget_message_text[^"]*"[^>]*>(.*?)</div>',
            block, re.DOTALL,
        )
        description = re.sub(r"<[^>]+>", "", text_m.group(1)).strip() if text_m else ""
        date_m = re.search(r'<time[^>]+datetime="([^"]+)"', block)
        views_m = re.search(r'<span[^>]+class="[^"]*tgme_widget_message_views[^"]*"[^>]*>([^<]+)<', block)
        thumb_m = re.search(r"background-image:url\('([^']+)'\)", block)
        posts.append({
            "external_id": msg_id,
            "description": description[:500],
            "thumbnail_url": thumb_m.group(1) if thumb_m else "",
            "post_url": f"https://t.me/{username}/{msg_id}",
            "view_count": _parse_tg_views(views_m.group(1)) if views_m else 0,
            "like_count": 0,
            "comment_count": 0,
            "share_count": 0,
            "posted_at": date_m.group(1) if date_m else None,
        })

    ids = [int(p["external_id"]) for p in posts if p["external_id"].isdigit()]
    return max(ids) if ids else 0, posts


# ─── YouTube ─────────────────────────────────────────────────────────────────

_YT_API_BASE = "https://www.googleapis.com/youtube/v3"


def fetch_youtube_channel(username: str) -> dict:
    username = username.lstrip("@")
    try:
        from django.conf import settings
        api_key = getattr(settings, "YOUTUBE_API_KEY", "") or ""
    except Exception:
        api_key = ""

    if api_key:
        return _fetch_youtube_api(username, api_key)
    return _fetch_youtube_scrape(username)


def _fetch_youtube_api(username: str, api_key: str) -> dict:
    """Fetch channel data via YouTube Data API v3 (requires API key)."""
    with httpx.Client(timeout=15.0) as client:
        # 1. Resolve channel — try @handle first, fall back to legacy username
        channel = None
        for params in (
            {"forHandle": f"@{username}"},
            {"forUsername": username},
        ):
            r = client.get(
                f"{_YT_API_BASE}/channels",
                params={**params, "part": "snippet,statistics", "key": api_key},
            )
            if r.status_code == 200:
                items = r.json().get("items", [])
                if items:
                    channel = items[0]
                    break

        if not channel:
            raise ValueError(f"YouTube @{username} не найден")

        channel_id = channel["id"]
        snippet = channel.get("snippet", {})
        stats = channel.get("statistics", {})

        display_name = snippet.get("title", username)
        bio = snippet.get("description", "")
        thumbs = snippet.get("thumbnails", {})
        avatar_url = (
            thumbs.get("high", {}).get("url")
            or thumbs.get("medium", {}).get("url")
            or thumbs.get("default", {}).get("url")
            or ""
        )
        follower_count = int(stats.get("subscriberCount", 0))
        video_count = int(stats.get("videoCount", 0))

        # 2. Fetch recent videos from the uploads playlist
        uploads_playlist = "UU" + channel_id[2:]  # UC… → UU…
        videos = _fetch_youtube_playlist_api(client, uploads_playlist, api_key)

    return {
        "display_name": display_name,
        "avatar_url": avatar_url,
        "bio": bio,
        "follower_count": follower_count,
        "following_count": 0,
        "like_count": 0,
        "post_count": video_count or len(videos),
        "_posts": videos,
    }


def _fetch_youtube_playlist_api(client: httpx.Client, playlist_id: str, api_key: str) -> list:
    """Get last 20 videos with full stats from a YouTube playlist."""
    r = client.get(
        f"{_YT_API_BASE}/playlistItems",
        params={
            "playlistId": playlist_id,
            "part": "snippet,contentDetails",
            "maxResults": 20,
            "key": api_key,
        },
    )
    if r.status_code != 200:
        return []

    items = r.json().get("items", [])
    video_ids = [
        item["contentDetails"]["videoId"]
        for item in items
        if item.get("contentDetails", {}).get("videoId")
    ]
    if not video_ids:
        return []

    # Fetch per-video statistics in one call (1 quota unit)
    stats_map: dict[str, dict] = {}
    rv = client.get(
        f"{_YT_API_BASE}/videos",
        params={"id": ",".join(video_ids), "part": "statistics", "key": api_key},
    )
    if rv.status_code == 200:
        for v in rv.json().get("items", []):
            stats_map[v["id"]] = v.get("statistics", {})

    videos = []
    for item in items:
        vid_id = item.get("contentDetails", {}).get("videoId")
        if not vid_id:
            continue
        sn = item.get("snippet", {})
        thumbs = sn.get("thumbnails", {})
        thumb = (
            thumbs.get("maxres", {}).get("url")
            or thumbs.get("high", {}).get("url")
            or thumbs.get("medium", {}).get("url")
            or thumbs.get("default", {}).get("url")
            or ""
        )
        s = stats_map.get(vid_id, {})
        videos.append({
            "external_id": vid_id,
            "description": sn.get("title", ""),
            "thumbnail_url": thumb,
            "post_url": f"https://www.youtube.com/watch?v={vid_id}",
            "view_count": int(s.get("viewCount", 0)),
            "like_count": int(s.get("likeCount", 0)),
            "comment_count": int(s.get("commentCount", 0)),
            "share_count": 0,
            "posted_at": sn.get("publishedAt"),
        })
    return videos


def _fetch_youtube_scrape(username: str) -> dict:
    """Fallback: scrape YouTube channel page + RSS (no API key needed)."""
    url = f"https://www.youtube.com/@{username}"
    with httpx.Client(headers=_HEADERS, follow_redirects=True, timeout=15.0) as client:
        r = client.get(url)
        if r.status_code == 404:
            raise ValueError(f"YouTube @{username} не найден")
        r.raise_for_status()
        html = r.text

    title_m = re.search(r'<meta property="og:title" content="([^"]+)"', html)
    display_name = title_m.group(1).strip() if title_m else username

    sub_m = (
        re.search(r'"content"\s*:\s*"([\d.,]+[KkMmBbTt]?)\s+subscribers?"', html) or
        re.search(r'"subscriberCountText":\{.*?"simpleText":"([^"]+)"', html, re.DOTALL) or
        re.search(r'"subscriberCountText":\{.*?"text":"([\d][^"]*)"', html, re.DOTALL)
    )
    follower_count = _parse_count(sub_m.group(1)) if sub_m else 0

    vid_m = (
        re.search(r'"content"\s*:\s*"(\d[\d,]*)\s+videos?"', html) or
        re.search(r'"videosCountText":\{.*?"simpleText":"([^"]+)"', html, re.DOTALL) or
        re.search(r'"videoCountText":\{.*?"runs":\[.*?\{"text":"(\d[^"]*)"', html, re.DOTALL)
    )
    explicit_video_count = _parse_count(vid_m.group(1)) if vid_m else 0

    avatar_m = (
        re.search(r'"avatar":\{"thumbnails":\[.*?\{"url":"(https://[^"]+)"', html, re.DOTALL) or
        re.search(r'<meta property="og:image" content="([^"]+)"', html)
    )
    avatar_url = avatar_m.group(1) if avatar_m else ""
    if avatar_url.startswith("//"):
        avatar_url = "https:" + avatar_url

    bio_m = re.search(r'<meta property="og:description" content="([^"]*)"', html)
    bio = bio_m.group(1).strip() if bio_m else ""

    cid_m = (
        re.search(r'"channelId":"(UC[^"]+)"', html) or
        re.search(r'"externalChannelId":"(UC[^"]+)"', html) or
        re.search(r'"browse_id","value":"(UC[^"]+)"', html) or
        re.search(r'"browseId":"(UC[^"]+)"', html) or
        re.search(r'/channel/(UC[a-zA-Z0-9_-]{22})', html)
    )
    channel_id = cid_m.group(1) if cid_m else None
    videos = _fetch_youtube_rss(channel_id) if channel_id else []

    return {
        "display_name": display_name,
        "avatar_url": avatar_url,
        "bio": bio,
        "follower_count": follower_count,
        "following_count": 0,
        "like_count": 0,
        "post_count": explicit_video_count or len(videos),
        "_posts": videos,
    }


def _fetch_youtube_rss(channel_id: str) -> list:
    """Fetch last 15 videos from the public RSS feed (no likes/comments)."""
    url = f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
    try:
        with httpx.Client(headers=_HEADERS, follow_redirects=True, timeout=10.0) as client:
            r = client.get(url)
            r.raise_for_status()
            xml = r.text
    except Exception:
        return []

    ns = {
        "atom": "http://www.w3.org/2005/Atom",
        "yt": "http://www.youtube.com/xml/schemas/2015",
        "media": "http://search.yahoo.com/mrss/",
    }
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        return []

    videos = []
    for entry in root.findall("atom:entry", ns):
        vid_id_el = entry.find("yt:videoId", ns)
        if vid_id_el is None:
            continue
        vid_id = vid_id_el.text
        title_el = entry.find("atom:title", ns)
        published_el = entry.find("atom:published", ns)
        thumb_el = entry.find("media:group/media:thumbnail", ns)
        stats_el = entry.find("media:group/media:community/media:statistics", ns)
        star_el = entry.find("media:group/media:community/media:starRating", ns)

        videos.append({
            "external_id": vid_id,
            "description": title_el.text if title_el is not None else "",
            "thumbnail_url": thumb_el.get("url", "") if thumb_el is not None else "",
            "post_url": f"https://www.youtube.com/watch?v={vid_id}",
            "view_count": int(stats_el.get("views", 0)) if stats_el is not None else 0,
            "like_count": int(star_el.get("count", 0)) if star_el is not None else 0,
            "comment_count": 0,
            "share_count": 0,
            "posted_at": published_el.text if published_el is not None else None,
        })
    return videos


# ─── Instagram ───────────────────────────────────────────────────────────────

def fetch_instagram_profile(username: str) -> dict:
    """Делегат в platforms.instagram.scraper (Playwright)."""
    from platforms.instagram.scraper import fetch_instagram_profile as _fetch
    return _fetch(username)


# ─── X (Twitter) ─────────────────────────────────────────────────────────────

def fetch_x_profile(username: str) -> dict:
    """Fetch X (Twitter) profile data via Playwright subprocess."""
    username = username.lstrip("@")
    return _run_worker(_X_WORKER, json.dumps({"username": username}), f"X @{username}")


# ─── Threads ──────────────────────────────────────────────────────────────────

def fetch_threads_profile(username: str) -> dict:
    """Fetch Threads profile data via Playwright subprocess."""
    username = username.lstrip("@")
    return _run_worker(_THREADS_WORKER, json.dumps({"username": username}), f"Threads @{username}")
