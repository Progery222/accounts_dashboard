"""Shared Rumble HTML/username parsing for worker and scraper."""
from __future__ import annotations

import json
import re


def normalize_username(raw: str) -> str:
    s = (raw or "").strip().lstrip("@")
    s = re.sub(r"^https?://(?:www\.)?rumble\.com/", "", s, flags=re.I)
    s = s.split("?", 1)[0].split("#", 1)[0].strip("/")
    parts = [p for p in s.split("/") if p]
    if parts and parts[0].lower() in {"c", "user"}:
        parts = parts[1:]
    if parts and parts[-1].lower() in {"about", "videos", "shorts", "livestreams"}:
        parts = parts[:-1]
    if not parts:
        raise ValueError("Некорректный Rumble username")
    return parts[0].strip()


def about_urls(username: str) -> list[str]:
    return [
        f"https://rumble.com/user/{username}/about",
        f"https://rumble.com/c/{username}/about",
    ]


def feed_urls(username: str) -> list[str]:
    return [
        f"https://rumble.com/user/{username}",
        f"https://rumble.com/c/{username}",
    ]


def parse_count(text: str) -> int:
    if not text:
        return 0
    raw = str(text).replace("\xa0", " ").replace("\u202f", " ").strip()
    m_short = re.match(r"^([\d][\d\s.,]*?)\s*([KMB])$", raw, flags=re.I)
    if m_short:
        num = m_short.group(1).replace(" ", "")
        suffix = m_short.group(2).upper()
        if "," in num and "." in num:
            num_norm = num.replace(",", "")
        elif "," in num:
            if num.count(",") > 1 or len(num.split(",")[-1]) == 3:
                num_norm = num.replace(",", "")
            else:
                num_norm = num.replace(",", ".")
        else:
            num_norm = num
        try:
            val = float(num_norm)
        except ValueError:
            val = 0.0
        if val > 10_000:
            digits = re.sub(r"[^\d]", "", num)
            return int(digits) if digits else 0
        mul = {"K": 1_000, "M": 1_000_000, "B": 1_000_000_000}[suffix]
        return int(val * mul)
    m = re.search(r"([\d][\d\s.,]*)", raw, flags=re.I)
    if not m:
        digits = re.sub(r"[^\d]", "", raw)
        return int(digits) if digits else 0
    num = m.group(1).replace(" ", "")
    digits = re.sub(r"[^\d]", "", num)
    return int(digits) if digits else 0


def extract_metric(html: str, label_pattern: str) -> int:
    patterns = [
        rf">\s*([0-9][0-9,\.\s]*[KMB]?)\s+{label_pattern}\s*<",
        rf"([0-9][0-9,\.\s]*[KMB]?)\s+{label_pattern}",
    ]
    for pattern in patterns:
        m = re.search(pattern, html, flags=re.I)
        if m:
            return parse_count(m.group(1))
    return 0


def is_not_found_html(html: str) -> bool:
    blob = (html or "")[:12_000].lower()
    if "404 not found" in blob:
        return True
    og = re.search(r'property="og:title" content="([^"]*)"', html or "", flags=re.I)
    return bool(og and og.group(1).strip().lower() == "404 not found")


def is_antibot_html(html: str) -> bool:
    blob = (html or "")[:10_000].lower()
    return any(
        m in blob
        for m in (
            "just a moment",
            "checking your browser",
            "cf-browser-verification",
            "challenge-platform",
        )
    )


def video_id_from_url(url: str) -> str:
    m = re.search(r"/shorts/([a-z0-9]+)", url, flags=re.I)
    if m:
        return m.group(1).lower()
    m = re.search(r"/([a-z0-9]+)-", url, flags=re.I)
    if m:
        return m.group(1).lower()
    m = re.search(r"/([a-z0-9]+)(?:$|[/?#])", url, flags=re.I)
    return m.group(1).lower() if m else url


def _post_url_from_tag(tag: str) -> str:
    raw_url = ""
    m = re.search(r'\burl="([^"]*)"', tag, flags=re.I)
    if m:
        raw_url = m.group(1).replace("&amp;", "&")
    shorts = re.search(r"https://rumble\.com/shorts/[a-z0-9]+", raw_url, re.I)
    if shorts:
        return shorts.group(0)
    normal = re.search(r"https://rumble\.com/v/[a-z0-9]+-", raw_url, re.I)
    if normal:
        return normal.group(0).split("?")[0]
    slug = re.search(r'url="https://rumble\.com/shorts/([a-z0-9]+)', tag, re.I)
    if slug:
        return f"https://rumble.com/shorts/{slug.group(1)}"
    return ""


def _valid_external_id(external_id: str) -> bool:
    eid = (external_id or "").strip().lower()
    return bool(re.fullmatch(r"[a-z0-9]{4,}", eid))


def _views_near_video_id(html: str, video_id: str) -> int:
    """Fallback: «15 views» в тексте карточки, если атрибут views пустой."""
    if not video_id:
        return 0
    needle = f'video-id="{video_id}"'
    pos = html.find(needle)
    if pos < 0:
        return 0
    window = html[max(0, pos - 400) : pos + 1200]
    m = re.search(r"•\s*([\d][\d\s.,]*[KMB]?)\s+views?\b", window, flags=re.I)
    if not m:
        m = re.search(r"\b([\d][\d\s.,]*[KMB]?)\s+views?\b", window, flags=re.I)
    return parse_count(m.group(1)) if m else 0


def _merge_thumbnail_post(existing: dict, incoming: dict) -> dict:
    merged = dict(existing)
    for field in ("description", "thumbnail_url", "post_url", "posted_at"):
        if not (merged.get(field) or "").strip() and (incoming.get(field) or "").strip():
            merged[field] = incoming[field]
    merged["view_count"] = max(int(merged.get("view_count") or 0), int(incoming.get("view_count") or 0))
    return merged


def extract_thumbnail_posts(html: str, *, limit: int = 30) -> list[dict]:
    by_id: dict[str, dict] = {}
    order: list[str] = []
    for tag in re.findall(r"<rum-video-thumbnail\b[^>]+>", html, flags=re.I):

        def attr(name: str) -> str:
            m = re.search(rf'\b{name}="([^"]*)"', tag, flags=re.I)
            return m.group(1) if m else ""

        video_id = attr("video-id")
        post_url = _post_url_from_tag(tag)
        external_id = video_id or (video_id_from_url(post_url) if post_url else "")
        if not _valid_external_id(external_id):
            continue
        if not post_url:
            post_url = f"https://rumble.com/v/{external_id}"
        view_count = parse_count(attr("views"))
        if view_count <= 0:
            view_count = _views_near_video_id(html, external_id)
        post = {
            "external_id": str(external_id),
            "description": attr("title"),
            "thumbnail_url": attr("src"),
            "post_url": post_url,
            "view_count": view_count,
            "like_count": 0,
            "comment_count": 0,
            "share_count": 0,
            "posted_at": attr("time") or None,
        }
        if external_id in by_id:
            by_id[external_id] = _merge_thumbnail_post(by_id[external_id], post)
            continue
        by_id[external_id] = post
        order.append(external_id)
        if len(order) >= limit:
            break
    return [by_id[eid] for eid in order]


def extract_json_ld_videos(html: str, *, limit: int = 30) -> list[dict]:
    videos: list[dict] = []
    for raw in re.findall(
        r'<script[^>]+type="application/ld\+json"[^>]*>(.*?)</script>',
        html,
        flags=re.I | re.DOTALL,
    ):
        try:
            data = json.loads(raw.strip())
        except Exception:
            continue
        nodes = data if isinstance(data, list) else [data]
        for node in nodes:
            if not isinstance(node, dict) or node.get("@type") != "VideoObject":
                continue
            url = str(node.get("url") or "").strip()
            if not url:
                continue
            if url.startswith("/"):
                url = "https://rumble.com" + url
            videos.append(
                {
                    "external_id": video_id_from_url(url),
                    "description": str(node.get("name") or "").strip(),
                    "thumbnail_url": str(node.get("thumbnailUrl") or "").strip(),
                    "post_url": url,
                    "view_count": int(node.get("interactionStatistic", {}).get("userInteractionCount", 0))
                    if isinstance(node.get("interactionStatistic"), dict)
                    else 0,
                    "like_count": 0,
                    "comment_count": 0,
                    "share_count": 0,
                    "posted_at": node.get("uploadDate"),
                }
            )
    dedup: dict[str, dict] = {}
    for item in videos:
        dedup[item["external_id"]] = item
    return list(dedup.values())[:limit]


def extract_posts(html: str, *, limit: int = 30) -> list[dict]:
    posts = extract_thumbnail_posts(html, limit=limit)
    if posts:
        return posts
    return extract_json_ld_videos(html, limit=limit)


def profile_from_html(
    *,
    username: str,
    about_html: str = "",
    feed_html: str = "",
) -> dict:
    html_for_meta = about_html or feed_html
    title_m = re.search(r'<meta property="og:title" content="([^"]+)"', html_for_meta, re.I)
    display_name = title_m.group(1).strip() if title_m else username
    if display_name.lower() == "404 not found":
        raise ValueError(f"Rumble @{username} не найден")

    bio_m = re.search(r'<meta property="og:description" content="([^"]*)"', html_for_meta, re.I)
    bio = bio_m.group(1).strip() if bio_m else ""

    avatar_m = re.search(r'<meta property="og:image" content="([^"]+)"', html_for_meta, re.I)
    avatar_url = avatar_m.group(1).strip() if avatar_m else ""

    follower_count = extract_metric(about_html, r"followers?") if about_html else 0
    channel_view_count = extract_metric(about_html, r"views?") if about_html else 0
    channel_video_count = extract_metric(about_html, r"videos?") if about_html else 0

    posts = extract_posts(feed_html) if feed_html else []
    post_count = channel_video_count or len(posts)
    post_views = sum(int(p.get("view_count") or 0) for p in posts)
    view_count = max(channel_view_count, post_views)

    return {
        "display_name": display_name,
        "avatar_url": avatar_url,
        "bio": bio,
        "follower_count": follower_count,
        "like_count": 0,
        "view_count": view_count,
        "post_count": post_count,
        "_posts": posts,
    }
