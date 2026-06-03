import html as _html
import json
import os
import re
import sys
from pathlib import Path

import httpx

from platforms.profile_unavailable import (
    PROFILE_UNAVAILABLE_MARK,
    is_profile_unavailable_error as is_instagram_profile_unavailable_error,
    user_visible_profile_unavailable_error as user_visible_instagram_error,
)
from platforms.instagram.posts_meta import annotate_instagram_posts_payload, instagram_max_posts
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


def raise_instagram_profile_unavailable(username: str, detail: str = "профиль удалён или недоступен") -> None:
    u = (username or "").lstrip("@")
    raise ValueError(f"{PROFILE_UNAVAILABLE_MARK}Instagram @{u}: {detail}")


def _html_indicates_removed_instagram_profile(html: str) -> bool:
    """HTML страница «профиль удалён / ссылка недействительна» (часто 200 OK)."""
    if not html or len(html) < 400:
        return False
    low = html.lower()
    if "sorry, this page isn't available" in low:
        return True
    if "the link you followed may be broken" in low and "instagram" in low:
        return True
    if "sorry, this page isn't available." in low:
        return True
    if "user not found" in low and "graphql" in low:
        return True
    if "ресурс" in low and "недоступен" in low and ("profile" in low or "профиль" in low):
        return True
    if "профиль удален" in low or "профиль удалён" in low:
        return True
    if "ссылка недействительна" in low and ("удален" in low or "удалён" in low or "профиль" in low):
        return True
    return False


def _message_indicates_removed_instagram_profile(message: str) -> bool:
    low = (message or "").lower()
    markers = (
        "sorry, this page isn't available",
        "this page isn't available",
        "the link you followed may be broken",
        "user not found",
        "instagram @",
        "страница не найдена",
        "профиль удал",
        "профиль недоступ",
        "ссылка недействительна",
    )
    return any(marker in low for marker in markers)


def _call_instagram_worker(payload: dict) -> dict:
    """
    Один долгоживущий процесс Instagram worker (`--daemon`); без таймаута на стороне
    пула — ответ приходит после завершения сценария Playwright.
    """
    if not _WORKER.exists():
        raise ValueError(f"Внутренняя ошибка: worker не найден по пути {_WORKER}")
    timeout_sec = 180.0
    try:
        from django.conf import settings

        timeout_sec = float(getattr(settings, "INSTAGRAM_WORKER_TIMEOUT_SEC", timeout_sec) or timeout_sec)
    except Exception:
        pass
    data = call_worker(_WORKER, payload, timeout_sec=timeout_sec)
    if "_posts" not in data:
        data["_posts"] = []
    return data


def _merge_posts_with_reels_grid_scraper(posts: list[dict], rows: list[dict]) -> list[dict]:
    """Дубликат логики из instagram/worker.py — нельзя импортировать worker (asyncio.run при импорте)."""
    posts = [dict(p) for p in (posts or [])]
    rows = rows or []
    by_sc_grid = {r["external_id"]: r for r in rows if r.get("external_id")}
    timeline_ids = {p.get("external_id") for p in posts if p.get("external_id")}

    out: list[dict] = []
    for p in posts:
        sid = p.get("external_id")
        if sid and sid in by_sc_grid:
            g = by_sc_grid[sid]
            tv = int(p.get("view_count") or 0)
            gv = int(g.get("view_count") or 0)
            p["view_count"] = max(tv, gv)
            if not p.get("thumbnail_url") and g.get("thumbnail_url"):
                p["thumbnail_url"] = g["thumbnail_url"]
            if not p.get("description") and g.get("description"):
                p["description"] = (g.get("description") or "")[:500]
        out.append(p)

    for r in rows:
        sc = r.get("external_id")
        if not sc or sc in timeline_ids:
            continue
        out.append({
            "external_id": sc,
            "description": (r.get("description") or "")[:500],
            "thumbnail_url": r.get("thumbnail_url") or "",
            "post_url": f"https://www.instagram.com/reel/{sc}/",
            "view_count": int(r.get("view_count") or 0),
            "like_count": int(r.get("like_count") or 0),
            "comment_count": 0,
            "share_count": 0,
            "posted_at": None,
        })
    return out


def _merge_reels_views_into_posts(username: str, posts: list[dict]) -> list[dict]:
    """Просмотры и недостающие рилсы с вкладки /reels/ (Playwright reels_views_only)."""
    u = username.lstrip("@")
    try:
        data = _call_instagram_worker({"username": u, "reels_views_only": True})
    except Exception as e:
        print(f"[instagram] слияние Reels пропущено для @{u}: {e}", file=sys.stderr)
        return posts

    grid = data.get("_reels_grid")
    if not grid:
        raw = data.get("_reels_views") or {}
        grid = []
        for k, v in raw.items():
            try:
                grid.append({
                    "external_id": str(k),
                    "view_count": int(v),
                    "thumbnail_url": "",
                    "description": "",
                })
            except (TypeError, ValueError):
                continue

    return _merge_posts_with_reels_grid_scraper(posts or [], grid)



def _apply_public_meta_to_profile(data: dict, username: str) -> dict:
    """Подставить счётчики из публичной meta, если они > 0."""
    out = dict(data)
    public = _fetch_public_meta_counts(username)
    for key in ("follower_count", "following_count", "post_count"):
        pub_v = int(public.get(key) or 0)
        if pub_v > 0:
            out[key] = pub_v
    return out


def fetch_instagram_profiles_bulk(usernames: list[str]) -> dict[str, dict]:
    """Несколько профилей: по одному полному проходу Playwright на аккаунт."""
    if not usernames:
        return {}

    def norm(x: str) -> str:
        return (x or "").lstrip("@").strip().lower()

    return {norm(u): fetch_instagram_profile(u) for u in usernames}


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


def _fetch_public_meta_counts(username: str) -> dict:
    """
    Read public counters from unauthenticated profile meta description.
    This can be more reliable than authenticated GraphQL/session fallbacks.
    """
    u = (username or "").lstrip("@").strip()
    if not u:
        return {"follower_count": 0, "following_count": 0, "post_count": 0}
    try:
        r = httpx.get(
            f"https://www.instagram.com/{u}/",
            headers=_HEADERS,
            follow_redirects=True,
            timeout=15,
        )
        if r.status_code != 200:
            return {"follower_count": 0, "following_count": 0, "post_count": 0}
        html = r.text or ""
        meta_desc = (
            re.search(r'<meta\s+name="description"\s+content="([^"]*)"', html)
            or re.search(r'<meta\s+property="og:description"\s+content="([^"]*)"', html)
        )
        if not meta_desc:
            return {"follower_count": 0, "following_count": 0, "post_count": 0}
        text = _html.unescape(meta_desc.group(1))
        # Order-independent extraction, e.g.:
        # "15 posts, 6 followers, 5 following - ..."
        f_m = re.search(r'([\d,.]+\s*[KMBkmb]?)\s+Followers?', text, re.I)
        fo_m = re.search(r'([\d,.]+\s*[KMBkmb]?)\s+Following', text, re.I)
        p_m = re.search(r'([\d,.]+\s*[KMBkmb]?)\s+Posts?', text, re.I)
        return {
            "follower_count": _parse_count(f_m.group(1)) if f_m else 0,
            "following_count": _parse_count(fo_m.group(1)) if fo_m else 0,
            "post_count": _parse_count(p_m.group(1)) if p_m else 0,
        }
    except Exception:
        return {"follower_count": 0, "following_count": 0, "post_count": 0}


def fetch_instagram_profile(username: str) -> dict:
    """
    Сбор Instagram через Playwright worker (instagram_state.json).
    Перед браузером — httpx-проверка «страница недоступна».
    """
    username = username.lstrip("@")
    try:
        public_url = f"https://www.instagram.com/{username}/"
        r = httpx.get(public_url, headers=_HEADERS, follow_redirects=True, timeout=15)
        if r.status_code == 404 or _html_indicates_removed_instagram_profile(r.text):
            raise_instagram_profile_unavailable(username)
    except ValueError:
        raise
    except Exception:
        pass

    try:
        data = _fetch_instagram_playwright(username)
    except ValueError as e:
        if _message_indicates_removed_instagram_profile(str(e)):
            raise_instagram_profile_unavailable(username)
        raise
    data = _apply_public_meta_to_profile(data, username)
    return annotate_instagram_posts_payload(data)


def _fetch_instagram_playwright(username: str) -> dict:
    """Playwright worker (instagram_state.json)."""
    try:
        return _call_instagram_worker({"username": username.lstrip("@")})
    except ValueError as e:
        # Worker may return plain text errors without PROFILE_UNAVAILABLE prefix.
        # Normalize known "page unavailable / not found" phrases so views can
        # reliably set account.profile_unavailable.
        if _message_indicates_removed_instagram_profile(str(e)):
            raise_instagram_profile_unavailable(username)
        raise
