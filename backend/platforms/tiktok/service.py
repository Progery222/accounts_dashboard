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
from platforms.profile_unavailable import PROFILE_UNAVAILABLE_MARK, is_profile_unavailable_error

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


def _merge_parsed_videos(primary: list[dict], secondary: list[dict]) -> list[dict]:
    """Объединить списки постов по id (SSR часто даёт только первую страницу, worker — остальное)."""
    by_id: dict[str, dict] = {}
    order: list[str] = []

    def _merge_into(cur: dict, other: dict) -> None:
        cur["play_count"] = max(int(cur.get("play_count") or 0), int(other.get("play_count") or 0))
        cur["like_count"] = max(int(cur.get("like_count") or 0), int(other.get("like_count") or 0))
        cur["comment_count"] = max(int(cur.get("comment_count") or 0), int(other.get("comment_count") or 0))
        cur["share_count"] = max(int(cur.get("share_count") or 0), int(other.get("share_count") or 0))
        ca = max(int(cur.get("created_at") or 0), int(other.get("created_at") or 0))
        if ca:
            cur["created_at"] = ca
        if not cur.get("description") and other.get("description"):
            cur["description"] = other["description"]
        if not cur.get("cover") and other.get("cover"):
            cur["cover"] = other["cover"]

    for v in primary:
        vid = str(v.get("id") or "")
        if not vid:
            continue
        if vid not in by_id:
            by_id[vid] = dict(v)
            order.append(vid)
        else:
            _merge_into(by_id[vid], v)

    for v in secondary:
        vid = str(v.get("id") or "")
        if not vid:
            continue
        if vid not in by_id:
            by_id[vid] = dict(v)
            order.append(vid)
        else:
            _merge_into(by_id[vid], v)

    return [by_id[i] for i in order]


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


def _tiktok_stat_to_int(raw) -> int:
    if raw is None:
        return 0
    if isinstance(raw, bool):
        return 0
    if isinstance(raw, (int, float)):
        return int(raw)
    return _parse_short_count(str(raw).strip())


def _parse_tiktok_universal_user_stats(html: str) -> tuple[dict, dict]:
    """Из HTML профиля: user и stats из webapp.user-detail (если есть)."""
    m = _UNIVERSAL_RE.search(html or "")
    if not m:
        return {}, {}
    try:
        scope = json.loads(m.group(1)).get("__DEFAULT_SCOPE__", {})
        ui = scope.get("webapp.user-detail", {}).get("userInfo", {})
        if not isinstance(ui, dict):
            return {}, {}
        user = ui.get("user") if isinstance(ui.get("user"), dict) else {}
        stats = ui.get("stats") if isinstance(ui.get("stats"), dict) else {}
        return user, stats
    except Exception:
        return {}, {}


def _user_stats_to_audience_meta(user: dict, stats: dict) -> dict:
    """Поля для строки audience (как в audience_scrape._tiktok_user_row_from_api_dict)."""
    out: dict = {}
    user = user if isinstance(user, dict) else {}
    stats = stats if isinstance(stats, dict) else {}
    sig = str(user.get("signature") or "").strip()
    if sig:
        out["bio"] = sig[:2000]
    nick = str(user.get("nickname") or "").strip()
    if nick:
        out["display_name"] = nick[:255]
    ext = str(user.get("secUid") or user.get("sec_uid") or user.get("id") or "").strip()
    if ext and "http" not in ext.lower():
        out["external_id"] = ext[:160]
    if user.get("privateAccount") or user.get("secret"):
        out["is_private"] = True
    fc = _tiktok_stat_to_int(stats.get("followerCount") or stats.get("follower_count"))
    fg = _tiktok_stat_to_int(stats.get("followingCount") or stats.get("following_count"))
    lk = _tiktok_stat_to_int(stats.get("heartCount") or stats.get("heart") or stats.get("diggCount"))
    out["follower_count"] = fc
    out["following_count"] = fg
    out["like_count"] = lk
    return out


def fetch_tiktok_oembed_profile_snippet(username: str) -> dict:
    """
    Лёгкий JSON без полного HTML (часто проходит, когда профиль отдаёт WAF-оболочку).
    Даёт в основном display_name (author_name).
    """
    username = (username or "").strip().lstrip("@").lower()
    if not username:
        return {}
    profile_url = f"https://www.tiktok.com/@{username}"
    try:
        r = httpx.get(
            "https://www.tiktok.com/oembed",
            params={"url": profile_url},
            headers={"User-Agent": _HEADERS["User-Agent"]},
            follow_redirects=True,
            timeout=15.0,
        )
        if r.status_code != 200:
            return {}
        data = r.json()
        if not isinstance(data, dict):
            return {}
        out: dict = {}
        an = str(data.get("author_name") or "").strip()
        if an:
            out["display_name"] = an[:255]
        return out
    except Exception:
        return {}


def fetch_tiktok_audience_member_meta_http(username: str) -> dict:
    """
    Метаданные профиля подписчика без Playwright: публичный HTML + oEmbed.
    Пустой dict — нет данных (WAF, 404). Не вызывает worker_pool.
    """
    username = (username or "").strip().lstrip("@").lower()
    if not username:
        return {}
    url = f"https://www.tiktok.com/@{username}"
    html = ""
    with httpx.Client(headers=_HEADERS, follow_redirects=True, timeout=25.0) as client:
        for attempt in range(3):
            response = client.get(url)
            if response.status_code == 404:
                return {}
            if response.status_code != 200:
                if attempt < 2:
                    time.sleep(1.2)
                    continue
            html = response.text
            if _UNIVERSAL_RE.search(html):
                break
            if attempt < 2:
                time.sleep(1.2)

    out: dict = {}
    user, stats = _parse_tiktok_universal_user_stats(html)
    if user or stats:
        out.update(_user_stats_to_audience_meta(user, stats))
    html_stats = _extract_tiktok_stats_from_html(html)
    if int(out.get("follower_count") or 0) == 0:
        out["follower_count"] = int(html_stats.get("follower_count") or 0)
    if int(out.get("following_count") or 0) == 0:
        out["following_count"] = int(html_stats.get("following_count") or 0)
    if int(out.get("like_count") or 0) == 0:
        out["like_count"] = int(html_stats.get("like_count") or 0)
    av = _extract_avatar_from_html(html)
    if av and not out.get("avatar_url"):
        out["avatar_url"] = av[:2048]

    if not str(out.get("display_name") or "").strip():
        out.update(fetch_tiktok_oembed_profile_snippet(username))
    return out


def _extract_avatar_from_html(html: str) -> str:
    raw_html = html or ""
    m = re.search(r'<meta\s+property="og:image"\s+content="([^"]+)"', raw_html, flags=re.I)
    if not m:
        return ""
    return _html.unescape(m.group(1)).strip()


def _avatar_score(url: str) -> int:
    """
    Prefer profile avatar endpoints over generic media thumbnails.
    TikTok profile avatars usually contain avt markers.
    """
    u = (url or "").strip().lower()
    if not u:
        return 0
    score = 1
    if "tiktokcdn" in u or "muscdn" in u:
        score += 1
    if "avt-" in u or "/avt/" in u or "tos-maliva-avt-" in u:
        score += 8
    # Penalize obvious post/video preview urls.
    if "cover" in u or "video" in u or "thumb" in u:
        score -= 3
    return score


def _pick_best_avatar(*candidates: str) -> str:
    best = ""
    best_score = 0
    for c in candidates:
        val = str(c or "").strip()
        if not val:
            continue
        s = _avatar_score(val)
        if s > best_score:
            best = val
            best_score = s
    return best


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
        # item_list с профиля иногда без author — не выкидываем всю ленту.
        if not author_username and not author_id:
            filtered.append(item)
    return filtered


def _videos_from_profile_html(html: str, username: str) -> list[dict]:
    """Ссылки /@user/video/id в SSR — когда itemList в JSON пустой, но посты есть на странице."""
    uname = (username or "").strip().lstrip("@").lower()
    if not uname or not html:
        return []
    seen: set[str] = set()
    out: list[dict] = []
    for pat in (
        re.compile(rf"https?://(?:www\.)?tiktok\.com/@{re.escape(uname)}/video/(\d+)", re.I),
        re.compile(rf"/@{re.escape(uname)}/video/(\d+)", re.I),
    ):
        for m in pat.finditer(html):
            vid = m.group(1)
            if not vid or vid in seen:
                continue
            seen.add(vid)
            out.append({
                "id": vid,
                "desc": "",
                "stats": {"playCount": 0, "diggCount": 0, "commentCount": 0, "shareCount": 0},
                "video": {"cover": ""},
                "createTime": 0,
            })
    return out


def _extract_author_stats_from_items(items: list[dict]) -> dict:
    """
    Read profile counters from item_list payloads (authorStats/authorStatsV2).
    This is reliable even when profile header DOM does not expose counters.
    """
    for item in items or []:
        if not isinstance(item, dict):
            continue
        stats = item.get("authorStats") or item.get("authorStatsV2") or {}
        if not isinstance(stats, dict):
            continue
        follower = int(stats.get("followerCount") or 0)
        following = int(stats.get("followingCount") or 0)
        likes = int(stats.get("heartCount") or stats.get("heart") or 0)
        videos = int(stats.get("videoCount") or 0)
        if follower or following or likes or videos:
            return {
                "follower_count": follower,
                "following_count": following,
                "like_count": likes,
                "video_count": videos,
            }
    return {
        "follower_count": 0,
        "following_count": 0,
        "like_count": 0,
        "video_count": 0,
    }


def _extract_author_avatar_from_items(
    items: list[dict],
    expected_username: str,
    expected_user_id: str = "",
) -> str:
    """
    Prefer avatar from item.author payloads (most reliable profile image source
    when page meta/DOM is noisy or points to media thumbnails).
    """
    exp_u = (expected_username or "").strip().lstrip("@").lower()
    exp_id = (expected_user_id or "").strip()
    for item in items or []:
        if not isinstance(item, dict):
            continue
        author = item.get("author", {}) if isinstance(item.get("author"), dict) else {}
        a_user = str(author.get("uniqueId") or "").strip().lower()
        a_id = str(author.get("id") or "").strip()
        if exp_u and a_user and a_user != exp_u:
            continue
        if exp_id and a_id and a_id != exp_id:
            continue
        for key in ("avatarLarger", "avatarMedium", "avatarThumb"):
            val = str(author.get(key) or "").strip()
            if val:
                return val
    return ""


def _is_tiktok_profile_unavailable_html(html: str) -> bool:
    text = (html or "").lower()
    if re.search(r"couldn.{0,3}t find this account", text):
        return True
    markers = (
        "could not find this account",
        "this account doesn",
        "account not found",
        "профиль не найден",
        "аккаунт не найден",
        "user not found",
    )
    return any(marker in text for marker in markers)


def _tiktok_worker_timeout_sec() -> float:
    raw = (os.environ.get("TIKTOK_WORKER_TIMEOUT_SEC") or "600").strip()
    try:
        return max(120.0, min(3600.0, float(raw)))
    except ValueError:
        return 600.0


def _tiktok_force_worker() -> bool:
    """TIKTOK_FORCE_WORKER=true — всегда вызывать Playwright при refresh (видимое окно на RDP)."""
    try:
        from django.conf import settings as _s

        return bool(getattr(_s, "TIKTOK_FORCE_WORKER", False))
    except Exception:
        pass
    raw = (os.environ.get("TIKTOK_FORCE_WORKER") or "").strip().lower()
    return raw in {"1", "true", "yes", "on", "y"}


def _run_worker(url: str, *, target_post_count: int = 0, sec_uid: str = "") -> tuple[list[dict], dict]:
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

    def _parse_worker_data(data) -> tuple[list[dict], dict]:
        if isinstance(data, list):
            return _filter_profile_items(data, _extract_username_from_url(url)), {}
        items = data.get("items") or []
        profile_stats = data.get("profile_stats") or {}
        return _filter_profile_items(items, _extract_username_from_url(url)), profile_stats

    try:
        payload = {"url": url, "target_post_count": int(target_post_count or 0)}
        if (sec_uid or "").strip():
            payload["sec_uid"] = str(sec_uid).strip()
        # Всегда используем daemon worker pool: одно окно TikTok переиспользуется
        # между аккаунтами и не закрывается после каждого refresh.
        data = call_worker(_WORKER, payload, timeout_sec=_tiktok_worker_timeout_sec())
        items, profile_stats = _parse_worker_data(data)
        if not items and int(target_post_count or 0) > 0:
            from platforms.tiktok.browser_profile import REFRESH_BROWSER_SECONDARY
            from platforms.worker_pool import call_worker_oneshot

            uname = _extract_username_from_url(url)
            print(
                f"[tiktok] worker без постов для @{uname}; повтор в гостевом Chrome…",
                file=sys.stderr,
            )
            data_guest = call_worker_oneshot(
                _WORKER,
                payload,
                timeout_sec=_tiktok_worker_timeout_sec(),
                extra_env={"TIKTOK_REFRESH_BROWSER_SLOT": REFRESH_BROWSER_SECONDARY},
            )
            items_guest, stats_guest = _parse_worker_data(data_guest)
            if items_guest:
                items, profile_stats = items_guest, stats_guest or profile_stats
        return items, profile_stats
    except Exception as e:
        # Worker may already return a user-facing "profile unavailable" style error.
        # Propagate it so API can mark account.profile_unavailable in a uniform way.
        if is_profile_unavailable_error(str(e)):
            raise
        from platforms.tiktok.captcha_batch import is_tiktok_captcha_stall_error

        if is_tiktok_captcha_stall_error(e):
            raise
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
            # Не ставим "profile unavailable" по одному HTML-ответу: TikTok часто
            # отдаёт антибот/ошибочную страницу, визуально похожую на "not found".
            # Окончательно решаем только после fallback через worker.
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
        # Не считаем это окончательным "профиль удалён": сначала пробуем worker.
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
    user_detail = scope.get("webapp.user-detail") or {}
    if isinstance(user_detail, dict):
        for subkey in ("itemList", "videoList"):
            items_candidate = user_detail.get(subkey)
            if isinstance(items_candidate, list) and items_candidate:
                print(
                    f"[tiktok] found video list in scope['webapp.user-detail'][{subkey!r}] "
                    f"({len(items_candidate)} items)"
                )
                raw = items_candidate
                break
        if not raw:
            item_module = user_detail.get("itemModule")
            if isinstance(item_module, dict) and item_module:
                module_items = [
                    v for v in item_module.values()
                    if isinstance(v, dict) and ("id" in v or "aweme_id" in v)
                ]
                if module_items:
                    print(
                        f"[tiktok] found video list in scope['webapp.user-detail']['itemModule'] "
                        f"({len(module_items)} items)"
                    )
                    raw = module_items
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
        html_videos = _videos_from_profile_html(html, username)
        if html_videos:
            print(f"[tiktok] found {len(html_videos)} video link(s) in HTML for @{username}")
            raw = html_videos

    if raw:
        raw = _filter_profile_items(raw, username, str(user.get("id") or ""))
        videos = _parse_videos(raw)

    worker_stats: dict = {}
    worker_author_stats = {
        "follower_count": 0,
        "following_count": 0,
        "like_count": 0,
        "video_count": 0,
    }
    video_count_stat = int(stats.get("videoCount") or 0)
    ssr_n = len(videos)
    # SSR почти всегда неполный (~одна страница item_list). Дополнительно TikTok часто
    # отдаёт videoCount=0 или заниженный — тогда без worker остаётся 16/3 постов вместо ~37.
    _FIRST_PAGE_CAP = 36
    need_posts_worker = (
        not videos
        or (video_count_stat > ssr_n)
        or (video_count_stat == 0 and ssr_n > 0)
        or (
            ssr_n > 0
            and ssr_n <= _FIRST_PAGE_CAP
            and (video_count_stat == 0 or video_count_stat <= _FIRST_PAGE_CAP)
        )
    )
    if _tiktok_force_worker():
        if not need_posts_worker:
            print(
                f"[tiktok] TIKTOK_FORCE_WORKER: forcing Playwright worker for @{username}",
                file=sys.stderr,
            )
        need_posts_worker = True

    worker_avatar = ""
    if need_posts_worker:
        if video_count_stat > 0:
            worker_post_target = max(video_count_stat, ssr_n + 1)
        else:
            # Нет официального счётчика — крутим ленту до «второй-третьей» страницы (~40+).
            worker_post_target = max(ssr_n + 28, 45)
        worker_items, worker_stats = _run_worker(
            url,
            target_post_count=worker_post_target,
            sec_uid=str(user.get("secUid") or ""),
        )
        worker_avatar = _extract_author_avatar_from_items(
            worker_items,
            username,
            str(user.get("id") or ""),
        )
        worker_author_stats = _extract_author_stats_from_items(worker_items)
        worker_videos = _parse_videos(worker_items)
        videos = _merge_parsed_videos(videos, worker_videos) if videos else worker_videos

    html_stats = _extract_tiktok_stats_from_html(html)
    follower_count = stats.get("followerCount", 0) or html_stats["follower_count"]
    following_count = stats.get("followingCount", 0) or html_stats["following_count"]
    like_count = (stats.get("heartCount") or stats.get("heart", 0)) or html_stats["like_count"]

    # If core counters are still empty, ask Playwright worker for DOM-derived stats
    # (XPath/CSS selectors on rendered profile header).
    if (follower_count == 0 or like_count == 0) and not worker_stats:
        _, worker_stats = _run_worker(
            url,
            target_post_count=0,
            sec_uid=str(user.get("secUid") or ""),
        )

    worker_follower = _parse_short_count(worker_stats.get("follower_text", "")) if worker_stats else 0
    worker_following = _parse_short_count(worker_stats.get("following_text", "")) if worker_stats else 0
    worker_likes = _parse_short_count(worker_stats.get("like_text", "")) if worker_stats else 0

    if follower_count == 0:
        follower_count = worker_author_stats["follower_count"] or worker_follower
    if following_count == 0:
        following_count = worker_author_stats["following_count"] or worker_following
    if like_count == 0:
        like_count = worker_author_stats["like_count"] or worker_likes
    if like_count == 0 and videos:
        # Fallback when TikTok hides profile "Likes" counter in DOM for this session.
        like_count = sum(int(v.get("like_count", 0) or 0) for v in videos)
    video_count = stats.get("videoCount", 0) or worker_author_stats["video_count"]
    avatar_url = _pick_best_avatar(
        worker_avatar,
        (worker_stats.get("avatar_url") if worker_stats else ""),
        user.get("avatarLarger", ""),
        user.get("avatarMedium", ""),
        _extract_avatar_from_html(html),
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
