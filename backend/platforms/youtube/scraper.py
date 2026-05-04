import re
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

_YT_API_BASE = "https://www.googleapis.com/youtube/v3"


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
