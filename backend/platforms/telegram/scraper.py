import asyncio
import re
import sys
from pathlib import Path

import httpx
from platforms.worker_pool import call_worker

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

_WORKER = Path(__file__).parent / "worker.py"


def _run_worker(worker_path: Path, payload: dict, platform_name: str) -> dict:
    if not worker_path.exists():
        raise ValueError(
            f"Внутренняя ошибка: worker не найден по пути {worker_path}"
        )
    data = call_worker(worker_path, payload)
    if "error" in data:
        raise ValueError(data["error"])
    if "_posts" not in data:
        data["_posts"] = []
    return data


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
    return _run_worker(_WORKER, {"username": username}, f"Telegram @{username}")


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
