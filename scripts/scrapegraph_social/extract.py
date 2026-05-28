"""
Детерминированное извлечение из HTML (как platforms/*, без cookies / Django).
"""

from __future__ import annotations

import html as html_lib
import json
import re
import xml.etree.ElementTree as ET
from typing import Any
from urllib.parse import urlparse

import httpx

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


def detect_platform(url: str) -> str:
    host = (urlparse(url).netloc or "").lower()
    if "youtube.com" in host or "youtu.be" in host:
        return "youtube"
    if "instagram.com" in host:
        return "instagram"
    if "facebook.com" in host or "fb.com" in host:
        return "facebook"
    if "tiktok.com" in host:
        return "tiktok"
    return "unknown"


def parse_count(text: str) -> int:
    if not text:
        return 0
    text = re.split(
        r"\s+(?:subscriber|member|follower|video|post|подписч)",
        text,
        flags=re.I,
    )[0].strip()
    m = re.match(r"^([\d]+(?:[.,][\d]+)?)\s*([KMBT])", text.replace(" ", "").upper())
    if m:
        try:
            num = float(m.group(1).replace(",", "."))
            return int(
                num
                * {"K": 1_000, "M": 1_000_000, "B": 1_000_000_000, "T": 1_000_000_000_000}[
                    m.group(2)
                ]
            )
        except (ValueError, KeyError):
            pass
    digits = re.sub(r"[^\d]", "", text)
    return int(digits) if digits else 0


def _dashboard_posts(posts: list[dict]) -> list[dict]:
    out = []
    for p in posts:
        eid = str(p.get("external_id") or "").strip()
        if not eid:
            continue
        out.append(
            {
                "external_id": eid,
                "post_url": str(p.get("post_url") or ""),
                "view_count": int(p.get("view_count") or 0),
                "like_count": int(p.get("like_count") or 0),
                "description": str(p.get("description") or "")[:500],
                "thumbnail_url": str(p.get("thumbnail_url") or "")[:2048],
            }
        )
    return out


def _wrap_dashboard(
    *,
    platform: str,
    username: str,
    display_name: str = "",
    follower_count: int = 0,
    post_count: int = 0,
    posts: list[dict] | None = None,
    notes: str = "",
    extraction: str = "deterministic",
    login_wall: bool = False,
) -> dict[str, Any]:
    posts = _dashboard_posts(posts or [])
    return {
        "platform": platform,
        "username": username,
        "display_name": display_name or username,
        "follower_count": int(follower_count or 0),
        "post_count": int(post_count or len(posts)),
        "posts": [
            {
                "post_url": p["post_url"],
                "view_count": p["view_count"],
                "like_count": p["like_count"],
                "external_id": p["external_id"],
            }
            for p in posts
        ],
        "_posts": posts,
        "notes": notes,
        "_extraction": extraction,
        "_login_wall": login_wall,
    }


# ── YouTube (как platforms/youtube/scraper.py, без API) ───────────────────────


def _youtube_channel_id(html: str) -> str | None:
    for pat in (
        r'"channelId":"(UC[^"]+)"',
        r'"externalChannelId":"(UC[^"]+)"',
        r'"browse_id","value":"(UC[^"]+)"',
        r'"browseId":"(UC[^"]+)"',
        r"/channel/(UC[a-zA-Z0-9_-]{22})",
    ):
        m = re.search(pat, html)
        if m:
            return m.group(1)
    return None


def _youtube_rss_videos(channel_id: str) -> list[dict]:
    url = f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
    try:
        with httpx.Client(headers=_HEADERS, follow_redirects=True, timeout=15.0) as client:
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
        vid_el = entry.find("yt:videoId", ns)
        if vid_el is None or not vid_el.text:
            continue
        vid_id = vid_el.text
        title_el = entry.find("atom:title", ns)
        published_el = entry.find("atom:published", ns)
        thumb_el = entry.find("media:group/media:thumbnail", ns)
        stats_el = entry.find("media:group/media:community/media:statistics", ns)
        star_el = entry.find("media:group/media:community/media:starRating", ns)
        videos.append(
            {
                "external_id": vid_id,
                "description": title_el.text if title_el is not None else "",
                "thumbnail_url": thumb_el.get("url", "") if thumb_el is not None else "",
                "post_url": f"https://www.youtube.com/watch?v={vid_id}",
                "view_count": int(stats_el.get("views", 0)) if stats_el is not None else 0,
                "like_count": int(star_el.get("count", 0)) if star_el is not None else 0,
            }
        )
    return videos


def extract_youtube(url: str, html: str) -> dict[str, Any]:
    m = re.search(r"youtube\.com/@([^/?#]+)", url, re.I)
    username = m.group(1) if m else ""
    title_m = re.search(r'<meta property="og:title" content="([^"]+)"', html)
    display_name = title_m.group(1).strip() if title_m else username

    sub_m = (
        re.search(r'"content"\s*:\s*"([\d.,]+[KkMmBbTt]?)\s+subscribers?"', html)
        or re.search(r'"subscriberCountText":\{.*?"simpleText":"([^"]+)"', html, re.DOTALL)
    )
    follower_count = parse_count(sub_m.group(1)) if sub_m else 0

    vid_m = re.search(r'"content"\s*:\s*"(\d[\d,]*)\s+videos?"', html)
    explicit_video_count = parse_count(vid_m.group(1)) if vid_m else 0

    channel_id = _youtube_channel_id(html)
    posts = _youtube_rss_videos(channel_id) if channel_id else []

    notes = ""
    if not posts and not follower_count:
        notes = "Нет RSS/счётчиков в HTML (возможен headless shell)"

    return _wrap_dashboard(
        platform="youtube",
        username=username,
        display_name=display_name,
        follower_count=follower_count,
        post_count=explicit_video_count or len(posts),
        posts=posts,
        notes=notes,
    )


# ── Instagram (фрагменты platforms/instagram/scraper.py) ──────────────────────


def _instagram_username(url: str) -> str:
    m = re.search(r"instagram\.com/([^/?#]+)", url, re.I)
    return (m.group(1) if m else "").lstrip("@").strip("/")


def _find_instagram_user(obj: Any, depth: int = 0) -> dict | None:
    if depth > 8 or not isinstance(obj, dict):
        return None
    if obj.get("username") and obj.get("id") and (
        obj.get("edge_followed_by")
        or obj.get("follower_count") is not None
        or obj.get("biography") is not None
        or obj.get("edge_owner_to_timeline_media")
    ):
        return obj
    for v in obj.values():
        if isinstance(v, dict):
            r = _find_instagram_user(v, depth + 1)
            if r:
                return r
        elif isinstance(v, list):
            for item in v:
                if isinstance(item, dict):
                    r = _find_instagram_user(item, depth + 1)
                    if r:
                        return r
    return None


def _instagram_from_graphql_user(user: dict, username: str) -> dict[str, Any]:
    display_name = user.get("full_name") or username
    follower_count = (
        user.get("edge_followed_by", {}).get("count") or user.get("follower_count") or 0
    )
    post_count = (
        user.get("edge_owner_to_timeline_media", {}).get("count")
        or user.get("media_count")
        or 0
    )
    posts = []
    for edge in (user.get("edge_owner_to_timeline_media", {}).get("edges") or [])[:24]:
        node = edge.get("node") or {}
        shortcode = node.get("shortcode") or node.get("code") or ""
        if not shortcode:
            continue
        is_reel = node.get("is_video") or "/reel/" in str(node.get("permalink") or "")
        path = "reel" if is_reel else "p"
        posts.append(
            {
                "external_id": shortcode,
                "post_url": f"https://www.instagram.com/{path}/{shortcode}/",
                "view_count": int(
                    node.get("video_view_count")
                    or node.get("video_play_count")
                    or node.get("play_count")
                    or 0
                ),
                "like_count": int(
                    node.get("edge_liked_by", {}).get("count")
                    or node.get("edge_media_preview_like", {}).get("count")
                    or 0
                ),
                "description": "",
                "thumbnail_url": node.get("thumbnail_src") or node.get("display_url") or "",
            }
        )
    return _wrap_dashboard(
        platform="instagram",
        username=username,
        display_name=display_name,
        follower_count=int(follower_count or 0),
        post_count=int(post_count or len(posts)),
        posts=posts,
    )


def extract_instagram(url: str, html: str) -> dict[str, Any]:
    username = _instagram_username(url)
    low = html.lower()[:300_000]
    login_wall = (
        "log in to instagram" in low
        or "/accounts/login/" in low
        or "login/?next=" in low
        or ('"login_redirect":true' in low.replace(" ", ""))
    )

    shared_m = re.search(r"window\._sharedData\s*=\s*(\{.+?\});\s*</script>", html, re.DOTALL)
    if shared_m:
        try:
            blob = json.loads(shared_m.group(1))
            user = (
                (blob.get("entry_data", {}).get("ProfilePage") or [{}])[0]
                .get("graphql", {})
                .get("user")
            )
            if user and user.get("id"):
                return _instagram_from_graphql_user(user, username)
        except Exception:
            pass

    for script_text in re.findall(
        r'<script\s+type="application/json"[^>]*>(.*?)</script>', html, re.DOTALL
    ):
        if len(script_text) < 50:
            continue
        try:
            blob = json.loads(script_text)
            user = _find_instagram_user(blob)
            if user:
                return _instagram_from_graphql_user(user, username)
        except Exception:
            continue

    meta_desc = re.search(
        r'<meta\s+(?:name="description"|property="og:description")\s+content="([^"]*)"',
        html,
    )
    follower_count = post_count = 0
    display_name = username
    og_title = re.search(r'<meta\s+property="og:title"\s+content="([^"]*)"', html)
    if og_title:
        t = html_lib.unescape(og_title.group(1))
        name_m = re.match(r"^(.+?)\s*(?:\(@[^)]+\))?\s*[•·]", t)
        display_name = name_m.group(1).strip() if name_m else t.split("•")[0].strip()

    if meta_desc:
        text = html_lib.unescape(meta_desc.group(1))
        f_m = re.search(r"([\d,.]+\s*[KMBkmb]?)\s+Followers?", text, re.I)
        p_m = re.search(r"([\d,.]+\s*[KMBkmb]?)\s+Posts?", text, re.I)
        if f_m:
            follower_count = parse_count(f_m.group(1))
        if p_m:
            post_count = parse_count(p_m.group(1))

    def _valid_ig_shortcode(s: str) -> bool:
        if not (9 <= len(s) <= 15):
            return False
        if s.lower() in ("reels", "explore", "accounts", "stories", "direct"):
            return False
        if re.match(r"^[a-z]{2}_[A-Z]{2}$", s):
            return False
        return bool(re.match(r"^[A-Za-z0-9_-]+$", s))

    raw_codes = (
        re.findall(r"/(?:reel|p)/([A-Za-z0-9_-]{9,15})", html)
        + re.findall(r'"shortcode"\s*:\s*"([A-Za-z0-9_-]{9,15})"', html)
    )
    shortcodes = [c for c in dict.fromkeys(raw_codes) if _valid_ig_shortcode(c)][:24]
    posts = [
        {
            "external_id": sc,
            "post_url": f"https://www.instagram.com/reel/{sc}/",
            "view_count": 0,
            "like_count": 0,
            "description": "",
            "thumbnail_url": "",
        }
        for sc in shortcodes
    ]

    notes = ""
    if login_wall and not posts and not follower_count:
        notes = "Стена логина Instagram (без cookies — нужен storage_state для parity с воркером)"

    return _wrap_dashboard(
        platform="instagram",
        username=username,
        display_name=display_name,
        follower_count=follower_count,
        post_count=post_count or len(posts),
        posts=posts,
        notes=notes,
        login_wall=login_wall,
    )


# ── TikTok (как platforms/tiktok/service.py, __UNIVERSAL_DATA_FOR_REHYDRATION__) ─

_TIKTOK_UNIVERSAL_RE = re.compile(
    r'<script id="__UNIVERSAL_DATA_FOR_REHYDRATION__"[^>]*>(.*?)</script>',
    re.DOTALL,
)


def _tiktok_username(url: str) -> str:
    m = re.search(r"/@([^/?#]+)", url, re.I)
    return m.group(1).strip().lower() if m else ""


def _tiktok_parse_short(text: str) -> int:
    if not text:
        return 0
    t = str(text).replace("\xa0", "").replace("\u202f", "").replace(",", "").strip()
    m = re.match(r"^([\d]+(?:\.[\d]+)?)\s*([KMB]?)$", t, flags=re.I)
    if not m:
        digits = re.sub(r"[^\d]", "", t)
        return int(digits) if digits else 0
    num = float(m.group(1))
    mult = {"": 1, "K": 1_000, "M": 1_000_000, "B": 1_000_000_000}[m.group(2).upper()]
    return int(num * mult)


def _tiktok_filter_items(items: list, username: str, user_id: str = "") -> list:
    u = (username or "").strip().lstrip("@").lower()
    uid = (user_id or "").strip()
    if not u and not uid:
        return items
    out = []
    for item in items:
        if not isinstance(item, dict):
            continue
        author = item.get("author") if isinstance(item.get("author"), dict) else {}
        au = str(author.get("uniqueId") or "").strip().lower()
        aid = str(author.get("id") or "").strip()
        if u and au and au == u:
            out.append(item)
        elif uid and aid and aid == uid:
            out.append(item)
    return out


def _tiktok_videos_from_items(items: list[dict], username: str) -> list[dict]:
    posts = []
    for item in items:
        vid = str(item.get("id") or "").strip()
        if not vid:
            continue
        stats = item.get("stats") if isinstance(item.get("stats"), dict) else {}
        posts.append(
            {
                "external_id": vid,
                "description": str(item.get("desc") or "")[:500],
                "thumbnail_url": str((item.get("video") or {}).get("cover") or "")[:2048],
                "post_url": f"https://www.tiktok.com/@{username}/video/{vid}",
                "view_count": int(stats.get("playCount") or 0),
                "like_count": int(stats.get("diggCount") or 0),
            }
        )
    return posts


def _tiktok_author_stats_from_items(items: list[dict]) -> dict[str, int]:
    for item in items:
        stats = item.get("authorStats") or item.get("authorStatsV2") or {}
        if not isinstance(stats, dict):
            continue
        fc = int(stats.get("followerCount") or 0)
        if fc or stats.get("videoCount"):
            return {
                "follower_count": fc,
                "like_count": int(stats.get("heartCount") or stats.get("heart") or 0),
                "post_count": int(stats.get("videoCount") or 0),
            }
    return {"follower_count": 0, "like_count": 0, "post_count": 0}


def _tiktok_stats_from_html(html: str) -> dict[str, int]:
    raw = html or ""
    fm = re.search(
        r'<strong[^>]*title="Followers"[^>]*>\s*([\d.,]+\s*[KMBkmb]?)',
        raw,
        re.I,
    )
    follower = _tiktok_parse_short(fm.group(1)) if fm else 0
    if not follower:
        m = re.search(r'"followerCount"\s*:\s*(\d+)', raw)
        follower = int(m.group(1)) if m else 0
    vm = re.search(r'"videoCount"\s*:\s*(\d+)', raw)
    video_count = int(vm.group(1)) if vm else 0
    lm = re.search(r'"heartCount"\s*:\s*(\d+)', raw)
    like_count = int(lm.group(1)) if lm else 0
    return {
        "follower_count": follower,
        "like_count": like_count,
        "post_count": video_count,
    }


def extract_tiktok(url: str, html: str) -> dict[str, Any]:
    username = _tiktok_username(url) or _tiktok_username(f"https://www.tiktok.com/@{url}")
    notes = ""
    login_wall = "captcha" in html.lower()[:100_000] and "verify" in html.lower()[:100_000]

    if _is_tiktok_unavailable(html):
        return _wrap_dashboard(
            platform="tiktok",
            username=username,
            notes="Профиль TikTok не найден или удалён",
            login_wall=False,
        )

    user: dict = {}
    stats: dict = {}
    scope: dict = {}
    raw_items: list = []

    m = _TIKTOK_UNIVERSAL_RE.search(html)
    if m:
        try:
            scope = json.loads(m.group(1)).get("__DEFAULT_SCOPE__", {})
            ui = scope.get("webapp.user-detail", {}).get("userInfo", {})
            if isinstance(ui, dict):
                user = ui.get("user") if isinstance(ui.get("user"), dict) else {}
                stats = ui.get("stats") if isinstance(ui.get("stats"), dict) else {}
        except Exception:
            scope = {}

        for key in ("webapp.video-list", "webapp.videofeed", "webapp.feed"):
            cand = scope.get(key, {})
            if isinstance(cand, dict):
                lst = cand.get("itemList") or cand.get("videoList") or []
                if lst:
                    raw_items = lst
                    break
        if not raw_items:
            for key, val in scope.items():
                if not isinstance(val, dict):
                    continue
                for subkey, subval in val.items():
                    if (
                        isinstance(subval, list)
                        and subval
                        and isinstance(subval[0], dict)
                        and "id" in subval[0]
                        and "stats" in subval[0]
                    ):
                        raw_items = subval
                        break
                if raw_items:
                    break

    user_id = str(user.get("id") or "")
    if raw_items:
        raw_items = _tiktok_filter_items(raw_items, username, user_id)

    posts = _tiktok_videos_from_items(raw_items, username)
    author_stats = _tiktok_author_stats_from_items(raw_items)
    html_stats = _tiktok_stats_from_html(html)

    follower_count = int(stats.get("followerCount") or 0) or author_stats["follower_count"]
    if not follower_count:
        follower_count = html_stats["follower_count"]
    like_count = int(stats.get("heartCount") or stats.get("heart") or 0) or author_stats["like_count"]
    if not like_count:
        like_count = html_stats["like_count"]
    post_count = int(stats.get("videoCount") or 0) or author_stats["post_count"] or len(posts)
    if not post_count:
        post_count = html_stats["post_count"] or len(posts)

    display_name = str(user.get("nickname") or "").strip() or username

    if not m:
        notes = "Нет __UNIVERSAL_DATA_FOR_REHYDRATION__ в HTML (нужен worker/cookies для полного списка)"
    elif not posts:
        notes = "Счётчики из SSR, список видео пуст в HTML (воркер даёт больше постов)"
    if login_wall:
        notes = (notes + " " if notes else "") + "Возможна капча TikTok"

    out = _wrap_dashboard(
        platform="tiktok",
        username=username,
        display_name=display_name,
        follower_count=follower_count,
        post_count=post_count,
        posts=posts,
        notes=notes.strip(),
        login_wall=login_wall,
    )
    out["like_count"] = like_count
    return out


def _is_tiktok_unavailable(html: str) -> bool:
    """Как platforms/tiktok/service.py; не матчить i18n-ключи в __UNIVERSAL_DATA__."""
    raw = html or ""
    m = _TIKTOK_UNIVERSAL_RE.search(raw)
    if m:
        try:
            scope = json.loads(m.group(1)).get("__DEFAULT_SCOPE__", {})
            ui = scope.get("webapp.user-detail", {}).get("userInfo", {})
            user = ui.get("user") if isinstance(ui.get("user"), dict) else {}
            if str(user.get("uniqueId") or "").strip():
                return False
            status = scope.get("webapp.user-detail", {}).get("statusCode")
            if status in (10221, 10225, 10227):
                return True
        except Exception:
            pass

    # Без SSR user — только явные маркеры вне JSON-блока rehydration
    stripped = _TIKTOK_UNIVERSAL_RE.sub("", raw)
    text = stripped.lower()
    if re.search(r"couldn.{0,3}t find this account", text):
        return True
    markers = (
        "could not find this account",
        "this account doesn",
        "account not found",
        "профиль не найден",
        "аккаунт не найден",
    )
    return any(marker in text for marker in markers)


# ── Facebook ────────────────────────────────────────────────────────────────


def extract_facebook(url: str, html: str) -> dict[str, Any]:
    login_wall = "login_data" in html or "CometLogInForm" in html or "device-based/regular/login" in html

    display_m = re.search(r"<title[^>]*>([^<]+)</title>", html, re.I)
    display_name = html_lib.unescape(display_m.group(1)).strip() if display_m else ""

    posts = []
    for reel_id in dict.fromkeys(re.findall(r"/reel/(\d+)", html)):
        view_count = 0
        ctx = re.search(
            rf"/reel/{re.escape(reel_id)}[^0-9]{{0,120}}?(\d{{1,12}})",
            html,
        )
        if ctx:
            view_count = int(ctx.group(1))
        posts.append(
            {
                "external_id": reel_id,
                "post_url": f"https://www.facebook.com/reel/{reel_id}/",
                "view_count": view_count,
                "like_count": 0,
                "description": "",
                "thumbnail_url": "",
            }
        )

    follower_count = 0
    fc_m = re.search(r"([\d,.]+\s*[KMBkmb]?)\s+(?:followers|подписчик)", html, re.I)
    if fc_m:
        follower_count = parse_count(fc_m.group(1))

    notes = ""
    if login_wall:
        notes = "Форма входа Facebook в HTML (без cookies полный parity с воркером недоступен)"

    return _wrap_dashboard(
        platform="facebook",
        username=url,
        display_name=display_name.replace(" | Facebook", "").strip(),
        follower_count=follower_count,
        post_count=len(posts),
        posts=posts,
        notes=notes,
        login_wall=login_wall,
    )


def extract_deterministic(url: str, html: str) -> dict[str, Any]:
    platform = detect_platform(url)
    if platform == "youtube":
        return extract_youtube(url, html)
    if platform == "instagram":
        return extract_instagram(url, html)
    if platform == "facebook":
        return extract_facebook(url, html)
    if platform == "tiktok":
        return extract_tiktok(url, html)
    return _wrap_dashboard(
        platform=platform,
        username=url,
        notes="Неподдерживаемый URL для запасного ScrapeGraph-пути",
    )


def is_sufficient(payload: dict[str, Any]) -> bool:
    """Достаточно данных без LLM: нужен хотя бы один пост с external_id."""
    if payload.get("_login_wall"):
        return False
    posts = payload.get("_posts") or []
    if len(posts) >= 1:
        return True
    # Счётчики без списка постов (типично IG /reels/ без graphql edges) — недостаточно.
    return False


def compact_llm_context(url: str, html: str, det: dict[str, Any]) -> str:
    """Компактный JSON для SmartScraperGraph (html_mode, source=строка)."""
    platform = det.get("platform") or detect_platform(url)
    video_ids = list(dict.fromkeys(re.findall(r'"videoId":"([^"]{11})"', html)))[:40]
    tiktok_ids = list(dict.fromkeys(re.findall(r'"id"\s*:\s*"(\d{15,22})"', html)))[:40]
    shortcodes = list(dict.fromkeys(re.findall(r"/(?:reel|p)/([A-Za-z0-9_-]{5,})", html)))[:40]
    reel_ids = list(dict.fromkeys(re.findall(r"/reel/(\d+)", html)))[:40]

    meta_desc = ""
    m = re.search(
        r'<meta\s+(?:name="description"|property="og:description")\s+content="([^"]*)"',
        html,
    )
    if m:
        meta_desc = html_lib.unescape(m.group(1))[:2000]

    blob = {
        "url": url,
        "platform": platform,
        "deterministic_partial": {
            "follower_count": det.get("follower_count"),
            "post_count": det.get("post_count"),
            "posts_found": len(det.get("_posts") or []),
            "notes": det.get("notes"),
        },
        "meta_description": meta_desc,
        "embedded_video_ids": video_ids,
        "embedded_shortcodes": shortcodes,
        "embedded_facebook_reel_ids": reel_ids,
        "embedded_tiktok_video_ids": tiktok_ids,
        "instructions": (
            "Return JSON: follower_count, post_count, posts[{post_url, view_count, like_count, external_id}]. "
            "Use ONLY numbers present in this blob. Do not invent. 0 if unknown."
        ),
    }
    return json.dumps(blob, ensure_ascii=False)
