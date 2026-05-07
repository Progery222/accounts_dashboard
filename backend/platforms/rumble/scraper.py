import json
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


def _parse_count(text: str) -> int:
    if not text:
        return 0
    raw = str(text).replace("\xa0", " ").replace("\u202f", " ").strip()
    m = re.search(r"([\d][\d\s.,]*[KMB]?)", raw, flags=re.I)
    if not m:
        return 0
    token = m.group(1).strip().replace(" ", "")
    short = re.match(r"^([\d]+(?:\.[\d]+)?)\s*([KMB])$", token, flags=re.I)
    if short:
        num = float(short.group(1))
        mul = {"K": 1_000, "M": 1_000_000, "B": 1_000_000_000}[short.group(2).upper()]
        return int(num * mul)
    digits = re.sub(r"[^\d]", "", token)
    return int(digits) if digits else 0


def _extract_metric(html: str, label_pattern: str) -> int:
    """
    Extracts values like:
      <span>119K Followers</span>
      <p>3,476,028 views</p>
      <p>730 videos</p>
    """
    # Keep the metric capture strict: only the numeric chunk immediately before label.
    patterns = [
        rf">\s*([0-9][0-9,\.\s]*[KMB]?)\s+{label_pattern}\s*<",
        rf"([0-9][0-9,\.\s]*[KMB]?)\s+{label_pattern}",
    ]
    for pattern in patterns:
        m = re.search(pattern, html, flags=re.I)
        if m:
            return _parse_count(m.group(1))
    return 0


def _video_id_from_url(url: str) -> str:
    m = re.search(r"/([a-z0-9]+)-", url, flags=re.I)
    if m:
        return m.group(1).lower()
    m = re.search(r"/([a-z0-9]+)(?:$|[/?#])", url, flags=re.I)
    return m.group(1).lower() if m else url


def _extract_json_ld_videos(html: str) -> list[dict]:
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
            if not isinstance(node, dict):
                continue
            if node.get("@type") != "VideoObject":
                continue
            url = str(node.get("url") or "").strip()
            if not url:
                continue
            if url.startswith("/"):
                url = "https://rumble.com" + url
            videos.append(
                {
                    "external_id": _video_id_from_url(url),
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
    return list(dedup.values())[:30]


def _run_worker(username: str, timeout: int = 120) -> dict:
    if not _WORKER.exists():
        raise ValueError(f"Внутренняя ошибка: worker не найден по пути {_WORKER}")
    data = call_worker(_WORKER, {"username": username})
    if "error" in data:
        raise ValueError(data["error"])
    if "_posts" not in data:
        data["_posts"] = []
    data.setdefault("_source", "worker")
    data.setdefault(
        "_quality_flags",
        {"about_parsed": False, "feed_parsed": bool(data.get("_posts")), "partial_posts": not bool(data.get("_posts"))},
    )
    return data


def _fetch_about_metrics(username: str) -> dict:
    about_candidates = [
        f"https://rumble.com/c/{username}/about",
        f"https://rumble.com/user/{username}/about",
    ]
    about_html = ""
    with httpx.Client(headers=_HEADERS, follow_redirects=True, timeout=20.0) as client:
        for url in about_candidates:
            r = client.get(url)
            if r.status_code >= 400:
                continue
            if "rumble" not in str(r.url):
                continue
            about_html = r.text
            break
    if not about_html:
        return {"follower_count": 0, "view_count": 0, "post_count": 0}
    return {
        "follower_count": _extract_metric(about_html, r"followers?"),
        "view_count": _extract_metric(about_html, r"views?"),
        "post_count": _extract_metric(about_html, r"videos?"),
    }


def fetch_rumble_profile(username: str) -> dict:
    username = username.strip().lstrip("@")
    username = re.sub(r"^https?://(?:www\.)?rumble\.com/", "", username, flags=re.I)
    username = username.split("?", 1)[0].split("#", 1)[0].strip("/")
    parts = [p for p in username.split("/") if p]
    if parts and parts[0].lower() in {"c", "user"}:
        parts = parts[1:]
    if parts and parts[-1].lower() == "about":
        parts = parts[:-1]
    if not parts:
        raise ValueError("Некорректный Rumble username")
    username = parts[0].strip()
    # Primary path: Playwright worker (bypasses Cloudflare challenge).
    try:
        worker_data = _run_worker(username)
        quality_flags = dict(worker_data.get("_quality_flags") or {})
        source = str(worker_data.get("_source") or "worker")
        try:
            about_metrics = _fetch_about_metrics(username)
            # About page metrics are the source of truth for channel-level counters.
            if about_metrics["follower_count"] > 0:
                worker_data["follower_count"] = about_metrics["follower_count"]
            if about_metrics["view_count"] > 0:
                worker_data["view_count"] = about_metrics["view_count"]
            if about_metrics["post_count"] > 0:
                worker_data["post_count"] = about_metrics["post_count"]
            quality_flags["about_http_refined"] = True
            if source == "worker":
                source = "mixed"
        except Exception as em:
            print(f"[rumble] about metrics refine failed for @{username}: {em}", file=sys.stderr)
            quality_flags["about_http_refined"] = False
        quality_flags["partial_posts"] = not bool(worker_data.get("_posts"))
        worker_data["_source"] = source
        worker_data["_quality_flags"] = quality_flags
        return worker_data
    except Exception as e:
        msg = str(e)
        anti_bot = ("антибот" in msg.lower()) or ("challenge" in msg.lower())
        if "антибот" in msg.lower() or "challenge" in msg.lower():
            print(
                f"[rumble] anti-bot loop for @{username}; falling back to HTTP parser",
                file=sys.stderr,
            )
        print(f"[rumble] worker fallback for @{username}: {e}", file=sys.stderr)

    about_candidates = [
        f"https://rumble.com/c/{username}/about",
        f"https://rumble.com/user/{username}/about",
    ]
    feed_candidates = [
        f"https://rumble.com/c/{username}",
        f"https://rumble.com/user/{username}",
        f"https://rumble.com/{username}",
    ]

    about_html = ""
    feed_html = ""
    with httpx.Client(headers=_HEADERS, follow_redirects=True, timeout=20.0) as client:
        for url in about_candidates:
            r = client.get(url)
            if r.status_code == 404:
                continue
            if r.status_code >= 400:
                continue
            if "rumble" not in str(r.url):
                continue
            about_html = r.text
            break

        for url in feed_candidates:
            r = client.get(url)
            if r.status_code == 404:
                continue
            if r.status_code >= 400:
                continue
            if "rumble" not in str(r.url):
                continue
            feed_html = r.text
            break

    if not about_html and not feed_html:
        raise ValueError(f"Rumble @{username} не найден")

    html_for_meta = about_html or feed_html
    title_m = re.search(r'<meta property="og:title" content="([^"]+)"', html_for_meta)
    display_name = title_m.group(1).strip() if title_m else username

    bio_m = re.search(r'<meta property="og:description" content="([^"]*)"', html_for_meta)
    bio = bio_m.group(1).strip() if bio_m else ""

    avatar_m = re.search(r'<meta property="og:image" content="([^"]+)"', html_for_meta)
    avatar_url = avatar_m.group(1).strip() if avatar_m else ""

    follower_count = _extract_metric(about_html, r"followers?") if about_html else 0
    channel_view_count = _extract_metric(about_html, r"views?") if about_html else 0
    channel_video_count = _extract_metric(about_html, r"videos?") if about_html else 0

    videos = _extract_json_ld_videos(feed_html) if feed_html else []
    post_count = channel_video_count or len(videos)

    return {
        "display_name": display_name,
        "avatar_url": avatar_url,
        "bio": bio,
        "follower_count": follower_count,
        "like_count": 0,
        "view_count": channel_view_count,
        "post_count": post_count,
        "_posts": videos,
        "_source": "httpx",
        "_quality_flags": {
            "anti_bot_detected": anti_bot,
            "about_parsed": bool(about_html),
            "feed_parsed": bool(feed_html),
            "partial_posts": not bool(videos),
            "jsonld_posts_used": bool(videos),
        },
    }
