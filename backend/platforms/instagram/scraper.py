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


def _instagram_creds_from_settings() -> tuple[str, str, str]:
    try:
        from django.conf import settings
        u = getattr(settings, "INSTAGRAM_USERNAME", "") or ""
        p = getattr(settings, "INSTAGRAM_PASSWORD", "") or ""
        sf = getattr(settings, "INSTAGRAM_SESSION_FILE", "") or ""
        return u, p, sf
    except Exception:
        return "", "", ""


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
            p["view_count"] = int(g.get("view_count") or 0)
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


def _fetch_instagram_counts_via_worker(username: str) -> dict:
    u = (username or "").lstrip("@").strip()
    if not u:
        return {"follower_count": 0, "following_count": 0, "post_count": 0}
    try:
        data = _call_instagram_worker({"username": u, "counts_only": True})
    except Exception:
        return {"follower_count": 0, "following_count": 0, "post_count": 0}
    return {
        "follower_count": int(data.get("follower_count") or 0),
        "following_count": int(data.get("following_count") or 0),
        "post_count": int(data.get("post_count") or 0),
    }


def _instaloader_login_once(insta_user: str, insta_pass: str, session_file: str):
    """Один залогиненный Instaloader (для батча нескольких профилей)."""
    import instaloader

    L = instaloader.Instaloader(
        download_pictures=False,
        download_videos=False,
        download_video_thumbnails=False,
        compress_json=False,
        save_metadata=False,
        quiet=True,
        max_connection_attempts=1,
    )
    session_path = Path(session_file) if session_file else None
    logged_in = False
    if session_path and session_path.exists():
        try:
            L.load_session_from_file(insta_user, str(session_path))
            logged_in = True
        except Exception:
            pass
    if not logged_in:
        L.login(insta_user, insta_pass)
        if session_path:
            session_path.parent.mkdir(parents=True, exist_ok=True)
            L.save_session_to_file(str(session_path))
    return L


def _instagram_instaloader_graphql_saturated(exc: BaseException) -> bool:
    """Instagram ограничил GraphQL (сессия жива, но нужен чекпоинт / снижение нагрузки)."""
    s = str(exc).lower()
    return any(
        m in s
        for m in (
            "feedback_required",
            "checkpoint_required",
            "challenge_required",
        )
    )


def _instaloader_profile_and_posts_raw(L, username: str) -> dict | tuple[dict, list[dict]]:
    """
    Профиль + посты без слияния Reels.
    Возвращает либо полный dict (как fetch_instagram_profile) для сложных кейсов,
    либо (summary_fields, posts) для последующего батч-Reels.
    """
    import instaloader as IL

    u = username.lstrip("@")
    # Instaloader GraphQL для ников с точкой часто ломается; без рекурсии в fetch_instagram_profile.
    if "." in u:
        try:
            return _fetch_instagram_via_html(u, L.context._session)
        except Exception as e:
            print(f"[instagram] via_html for @{u}: {e}", file=sys.stderr)
            return _fetch_instagram_playwright(u)

    profile = None
    try:
        profile = IL.Profile.from_username(L.context, u)
    except IL.exceptions.ProfileNotExistsException:
        pass
    except Exception as e:
        if _instagram_instaloader_graphql_saturated(e):
            print(
                f"[instagram] Instaloader GraphQL ограничен для @{u}, переход на Playwright: {e}",
                file=sys.stderr,
            )
            return _fetch_instagram_playwright(u)
        raise ValueError(f"Ошибка получения Instagram @{u}: {e}") from e

    if profile is None:
        try:
            return _fetch_instagram_via_html(u, L.context._session)
        except Exception as e:
            print(f"[instagram] API без профиля, fallback @{u}: {e}", file=sys.stderr)
            return _fetch_instagram_playwright(u)

    posts: list[dict] = []
    try:
        for post in profile.get_posts():
            if len(posts) >= 12:
                break
            posts.append({
                "external_id": post.shortcode,
                "description": (post.caption or "")[:500],
                "thumbnail_url": post.url,
                "post_url": f"https://www.instagram.com/p/{post.shortcode}/",
                "view_count": post.video_view_count if post.is_video else 0,
                "like_count": post.likes,
                "comment_count": post.comments,
                "share_count": 0,
                "posted_at": post.date_utc.isoformat() if post.date_utc else None,
            })
    except Exception as e:
        if _instagram_instaloader_graphql_saturated(e):
            print(
                f"[instagram] Instaloader лента ограничена для @{u}, переход на Playwright: {e}",
                file=sys.stderr,
            )
            return _fetch_instagram_playwright(u)
        print(f"[instagram] posts error for @{u}: {e}", file=sys.stderr)

    summary = {
        "display_name": profile.full_name or u,
        "avatar_url": profile.profile_pic_url,
        "bio": profile.biography or "",
        "follower_count": profile.followers,
        "following_count": profile.followees,
        "like_count": 0,
        "post_count": profile.mediacount,
    }
    return summary, posts


def fetch_instagram_profiles_bulk(usernames: list[str]) -> dict[str, dict]:
    """
    Несколько Instagram-профилей: один Instaloader + одно окно Playwright для всех /reels/.
    Ключи — username в нижнем регистре без @.
    """
    if not usernames:
        return {}

    def norm(x: str) -> str:
        return (x or "").lstrip("@").strip().lower()

    if len(usernames) == 1:
        u0 = usernames[0]
        return {norm(u0): fetch_instagram_profile(u0)}

    insta_user, insta_pass, session_file = _instagram_creds_from_settings()
    if not (insta_user and insta_pass):
        return {norm(u): fetch_instagram_profile(u) for u in usernames}

    L = _instaloader_login_once(insta_user, insta_pass, session_file)

    complete: dict[str, dict] = {}
    pending: dict[str, tuple[dict, list]] = {}

    for raw in usernames:
        key = norm(raw)
        try:
            chunk = _instaloader_profile_and_posts_raw(L, raw)
        except Exception:
            complete[key] = fetch_instagram_profile(raw)
            continue
        if isinstance(chunk, dict):
            complete[key] = chunk
        else:
            summary, posts = chunk
            pending[key] = (summary, posts)

    batch_labels = [u.lstrip("@") for u in usernames if norm(u) in pending]

    if len(batch_labels) > 1:
        try:
            data = _call_instagram_worker(
                {"usernames": batch_labels, "reels_views_only": True},
            )
        except Exception as e:
            print(f"[instagram] batch reels worker failed: {e}", file=sys.stderr)
            for key, (summary, posts) in pending.items():
                summary = dict(summary)
                summary["_posts"] = _merge_reels_views_into_posts(
                    next(u for u in usernames if norm(u) == key),
                    posts,
                )
                complete[key] = summary
        else:
            grids = data.get("_batch_reels_grids") or {}
            for key, (summary, posts) in pending.items():
                rows = grids.get(key) or []
                summary = dict(summary)
                summary["_posts"] = _merge_posts_with_reels_grid_scraper(posts or [], rows)
                complete[key] = summary
    else:
        for key, (summary, posts) in pending.items():
            u_for_merge = next(x for x in usernames if norm(x) == key)
            summary = dict(summary)
            summary["_posts"] = _merge_reels_views_into_posts(u_for_merge, posts)
            complete[key] = summary

    return complete


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
    Fetch Instagram profile.
    With INSTAGRAM_USERNAME/PASSWORD: instaloader + один запуск Playwright на /reels/ для просмотров.
    Run `python manage.py setup_instagram_auth` once to create the session file.
    Без кредов — полный сбор через Playwright (профиль + Reels).
    """
    username = username.lstrip("@")
    # Fast pre-check for "page unavailable" HTML before any heavier scraper path.
    # This catches removed/banned/not-found profiles even when Instaloader returns
    # a "successful" shell with empty counters.
    try:
        public_url = f"https://www.instagram.com/{username}/"
        r = httpx.get(public_url, headers=_HEADERS, follow_redirects=True, timeout=15)
        if r.status_code == 404 or _html_indicates_removed_instagram_profile(r.text):
            raise_instagram_profile_unavailable(username)
    except ValueError:
        raise
    except Exception:
        # Best-effort only: if network is flaky, continue with normal scraper flow.
        pass
    try:
        from django.conf import settings
        insta_user = getattr(settings, "INSTAGRAM_USERNAME", "")
        insta_pass = getattr(settings, "INSTAGRAM_PASSWORD", "")
        session_file = getattr(settings, "INSTAGRAM_SESSION_FILE", "")
        force_playwright = bool(getattr(settings, "INSTAGRAM_FORCE_PLAYWRIGHT", False))
    except Exception:
        insta_user = insta_pass = session_file = ""
        force_playwright = False

    # Optional local override to troubleshoot/update via visible browser flow.
    if not force_playwright:
        force_playwright = os.getenv("INSTAGRAM_FORCE_PLAYWRIGHT", "").strip().lower() in {
            "1", "true", "yes", "on",
        }

    if force_playwright:
        return _fetch_instagram_playwright(username)

    if insta_user and insta_pass:
        # Instaloader для профиля и постов; затем один проход Playwright по /reels/ для просмотров.
        # Если это падает не ValueError — сессия сломана; перезапусти setup_instagram_auth.
        return _fetch_instagram_instaloader(username, insta_user, insta_pass, session_file)

    # No credentials configured at all — fall back to Playwright
    return _fetch_instagram_playwright(username)


def _fetch_instagram_instaloader(username: str, insta_user: str, insta_pass: str, session_file: str) -> dict:
    L = _instaloader_login_once(insta_user, insta_pass, session_file)
    chunk = _instaloader_profile_and_posts_raw(L, username)
    if isinstance(chunk, dict):
        return chunk
    summary, posts = chunk
    out = dict(summary)
    out["_posts"] = _merge_reels_views_into_posts(username, posts)
    public_counts = _fetch_public_meta_counts(username)
    # Prefer public meta counters when they are available and differ.
    # In practice this fixes occasional stale/shifted counters from authenticated flows.
    if int(public_counts.get("follower_count") or 0) > 0:
        out["follower_count"] = int(public_counts["follower_count"])
    if int(public_counts.get("following_count") or 0) > 0:
        out["following_count"] = int(public_counts["following_count"])
    if int(public_counts.get("post_count") or 0) > 0:
        out["post_count"] = int(public_counts["post_count"])
    worker_counts = _fetch_instagram_counts_via_worker(username)
    if int(worker_counts.get("follower_count") or 0) > 0:
        out["follower_count"] = int(worker_counts["follower_count"])
    if int(worker_counts.get("following_count") or 0) > 0:
        out["following_count"] = int(worker_counts["following_count"])
    if int(worker_counts.get("post_count") or 0) > 0:
        out["post_count"] = int(worker_counts["post_count"])
    # Instaloader иногда отдает "пустой" профиль (все ключевые счётчики = 0)
    # без явной ошибки. В таком случае пробуем Playwright, чтобы получить
    # актуальные данные в том же refresh-запросе.
    if (
        int(out.get("follower_count") or 0) == 0
        and int(out.get("post_count") or 0) == 0
        and len(out.get("_posts") or []) == 0
    ):
        print(
            f"[instagram] instaloader returned empty profile for @{username}; falling back to Playwright",
            file=sys.stderr,
        )
        return _fetch_instagram_playwright(username)
    return out


def _fetch_instagram_via_html(username: str, session) -> dict:
    """
    Fetch Instagram profile for new-style / dot-domain usernames
    (e.g. 'blockchainsports.arena') that instaloader's API doesn't support.

    Strategy:
    1. Authenticated ?__a=1 → full GraphQL profile + posts (fast, sometimes rate-limited)
    2. Unauthenticated httpx page → meta tags reliably include "88.4K Followers, …"
       (Instagram strips counts from meta description when the request carries cookies)
    """
    import html as _html
    base_url = f"https://www.instagram.com/{username}/"

    # ── 1. Authenticated ?__a=1 ───────────────────────────────────────────────
    try:
        r = session.get(
            base_url,
            params={"__a": "1", "__d": "dis"},
            headers={
                **_HEADERS,
                "Accept": "application/json, text/javascript, */*; q=0.01",
                "X-Requested-With": "XMLHttpRequest",
                "X-IG-App-ID": "936619743392459",
            },
            timeout=15,
        )
        if r.status_code == 200:
            try:
                blob = r.json()
                user = (
                    blob.get("graphql", {}).get("user")
                    or blob.get("data", {}).get("user")
                    or blob.get("user")
                )
                if user and user.get("id"):
                    return _parse_instagram_graphql_user(user, username)
            except Exception:
                pass
    except Exception as e:
        print(f"[instagram] __a=1 failed for @{username}: {e}", file=sys.stderr)

    # ── 2. Unauthenticated HTML fetch ─────────────────────────────────────────
    # For most public accounts Instagram embeds "88.4K Followers, …" in the
    # unauthenticated meta description. Some new-style / dot-domain accounts
    # redirect to the login page — we detect that and fall through to a fallback.
    r_pub = None
    login_redirect = True
    try:
        r_pub = httpx.get(base_url, headers=_HEADERS, follow_redirects=True, timeout=15)
        if r_pub.status_code == 404:
            raise_instagram_profile_unavailable(username, "страница не найдена (404)")
        login_redirect = "accounts/login" in str(r_pub.url)
    except ValueError:
        raise
    except Exception as e:
        print(f"[instagram] unauthenticated fetch failed for @{username}: {e}", file=sys.stderr)

    if not login_redirect and r_pub is not None and r_pub.status_code == 200:
        html = r_pub.text
    else:
        # Authenticated HTML fallback — Instagram strips follower counts here,
        # so if we can't extract them we'll raise ValueError to preserve DB data.
        try:
            r_auth = session.get(base_url, headers={
                **_HEADERS,
                "Sec-Fetch-Site": "none",
                "Sec-Fetch-Mode": "navigate",
            }, timeout=15)
            if r_auth.status_code == 404:
                raise_instagram_profile_unavailable(username, "страница не найдена (404)")
            html = r_auth.text if r_auth.status_code == 200 else ""
        except ValueError:
            raise
        except Exception:
            html = ""

    if not html:
        raise ValueError(f"Instagram @{username}: данные временно недоступны, попробуй позже")

    if _html_indicates_removed_instagram_profile(html):
        raise_instagram_profile_unavailable(username)

    # ── 2a. Try embedded window._sharedData JSON ──────────────────────────────
    shared_m = re.search(r'window\._sharedData\s*=\s*(\{.+?\});\s*</script>', html, re.DOTALL)
    if shared_m:
        try:
            blob = json.loads(shared_m.group(1))
            user = (
                (blob.get("entry_data", {}).get("ProfilePage") or [{}])[0]
                .get("graphql", {}).get("user")
            )
            if user and user.get("id"):
                return _parse_instagram_graphql_user(user, username)
        except Exception:
            pass

    # ── 2a2. Try <script type="application/json"> blobs ───────────────────────
    for script_text in re.findall(r'<script\s+type="application/json"[^>]*>(.*?)</script>', html, re.DOTALL):
        try:
            blob = json.loads(script_text)
            # Walk the blob looking for a user node with 'id' and 'username' keys
            def _find_user(obj, depth=0):
                if depth > 6 or not isinstance(obj, dict):
                    return None
                if obj.get("username") and obj.get("id") and (
                    obj.get("edge_followed_by") or obj.get("follower_count") is not None
                    or obj.get("biography") is not None
                ):
                    return obj
                for v in obj.values():
                    if isinstance(v, (dict, list)):
                        r = _find_user(v, depth + 1) if isinstance(v, dict) else next(
                            filter(None, (_find_user(i, depth + 1) for i in v if isinstance(i, dict))), None
                        )
                        if r:
                            return r
                return None
            user = _find_user(blob)
            if user:
                return _parse_instagram_graphql_user(user, username)
        except Exception:
            pass

    # ── 2a3. Search for user JSON in any inline script ────────────────────────
    for pat in (
        r'"username"\s*:\s*"' + re.escape(username) + r'".*?"follower_count"\s*:\s*(\d+)',
        r'"user"\s*:\s*\{[^}]*"username"\s*:\s*"' + re.escape(username) + r'"',
    ):
        m = re.search(pat, html, re.DOTALL)
        if m:
            # Try to extract a JSON object around the match
            start = html.rfind('{', 0, m.start())
            if start != -1:
                # Walk forward to find matching brace
                depth = 0
                for i, ch in enumerate(html[start:start + 20000]):
                    if ch == '{':
                        depth += 1
                    elif ch == '}':
                        depth -= 1
                        if depth == 0:
                            try:
                                candidate = json.loads(html[start:start + i + 1])
                                def _find_user2(obj, d=0):
                                    if d > 4 or not isinstance(obj, dict):
                                        return None
                                    if obj.get("username") == username and obj.get("id"):
                                        return obj
                                    for v in obj.values():
                                        r2 = _find_user2(v, d + 1) if isinstance(v, dict) else next(
                                            filter(None, (_find_user2(i2, d + 1) for i2 in v if isinstance(i2, dict))), None
                                        ) if isinstance(v, list) else None
                                        if r2:
                                            return r2
                                    return None
                                user = _find_user2(candidate)
                                if user:
                                    return _parse_instagram_graphql_user(user, username)
                            except Exception:
                                pass
                            break

    # ── 2b. og:/meta tag fallback ─────────────────────────────────────────────
    og_title = re.search(r'<meta\s+property="og:title"\s+content="([^"]*)"', html)
    og_image = re.search(r'<meta\s+property="og:image"\s+content="([^"]*)"', html)
    # meta name="description" → "88.4K Followers, 3,049 Following, 51 Posts - Bio"
    meta_desc = (
        re.search(r'<meta\s+name="description"\s+content="([^"]*)"', html)
        or re.search(r'<meta\s+property="og:description"\s+content="([^"]*)"', html)
    )

    if not og_title and not meta_desc:
        # Last resort: Playwright worker (renders the full SPA)
        try:
            return _fetch_instagram_playwright(username)
        except Exception as _pw_exc:
            print(f"[instagram] Playwright fallback failed for @{username}: {_pw_exc}", file=sys.stderr)
        # Не помечаем как «удалён» — может быть временная разметка / антибот.
        raise ValueError(f"Instagram @{username} не найден (не удалось разобрать страницу)")

    display_name = username
    if og_title:
        t = _html.unescape(og_title.group(1))
        name_m = re.match(r'^(.+?)\s*(?:\(@[^)]+\))?\s*[•·]', t)
        display_name = name_m.group(1).strip() if name_m else t.split("•")[0].split("(")[0].strip()

    follower_count = following_count = post_count = 0
    has_counts = False
    bio = ""
    if meta_desc:
        text = _html.unescape(meta_desc.group(1))
        # _parse_count() handles "88.4K" → 88400 and "1,234" → 1234
        f_m  = re.search(r'([\d,.]+\s*[KMBkmb]?)\s+Follower', text, re.I)
        fo_m = re.search(r'([\d,.]+\s*[KMBkmb]?)\s+Following', text, re.I)
        p_m  = re.search(r'([\d,.]+\s*[KMBkmb]?)\s+Post', text, re.I)
        if f_m:
            follower_count = _parse_count(f_m.group(1))
            has_counts = True
        if fo_m:
            following_count = _parse_count(fo_m.group(1))
        if p_m:
            post_count = _parse_count(p_m.group(1))
        parts = text.split(" - ", 1)
        if len(parts) > 1:
            bio = parts[1].strip()

    avatar_url = og_image.group(1) if og_image else ""

    # ── 2c. Extract avatar from embedded JavaScript ───────────────────────────
    # Authenticated HTML often doesn't include og:image, but Instagram always
    # embeds profile_pic_url somewhere in the page's inline JSON payloads.
    if not avatar_url:
        for pat in (
            r'"profile_pic_url_hd"\s*:\s*"(https?://scontent[^"\\]+)"',
            r'"profile_pic_url"\s*:\s*"(https?://scontent[^"\\]+)"',
            r'"profile_pic_url_hd"\s*:\s*"(https?://[^"\\]+)"',
            r'"profile_pic_url"\s*:\s*"(https?://[^"\\]+)"',
        ):
            m = re.search(pat, html)
            if m:
                avatar_url = m.group(1).replace("\\u0026", "&").replace("\\/", "/")
                break

    # When using authenticated HTML (login_redirect path), Instagram strips
    # follower counts — raise ValueError to preserve existing DB data.
    # Exception: if we found an avatar URL, do a partial update to save it.
    if login_redirect and not has_counts:
        if avatar_url:
            return {
                "_partial": True,   # signal to _apply_refresh: skip stat fields
                "avatar_url": avatar_url,
                "display_name": display_name or None,
                "_posts": [],
            }
        raise ValueError(
            f"Instagram @{username}: статистика временно недоступна, данные не изменены."
        )

    return {
        "display_name": display_name,
        "avatar_url": avatar_url,
        "bio": bio,
        "follower_count": follower_count,
        "following_count": following_count,
        "like_count": 0,
        "post_count": post_count,
        "_posts": [],  # posts not available via plain HTML; likes come from existing DB posts
    }


def _parse_instagram_graphql_user(user: dict, username: str) -> dict:
    """Convert an Instagram GraphQL user node into the standard scraper dict."""
    display_name = user.get("full_name") or username
    avatar_url   = (
        user.get("profile_pic_url_hd")
        or (user.get("hd_profile_pic_url_info") or {}).get("url")
        or user.get("profile_pic_url")
        or ""
    )
    bio          = user.get("biography") or ""
    follower_count  = (
        user.get("edge_followed_by", {}).get("count")
        or user.get("follower_count") or 0
    )
    following_count = (
        user.get("edge_follow", {}).get("count")
        or user.get("following_count") or 0
    )
    post_count = (
        user.get("edge_owner_to_timeline_media", {}).get("count")
        or user.get("media_count") or 0
    )

    posts = []
    for edge in (user.get("edge_owner_to_timeline_media", {}).get("edges") or [])[:20]:
        node = edge.get("node", {})
        shortcode = node.get("shortcode", "")
        if not shortcode:
            continue
        caption_edges = node.get("edge_media_to_caption", {}).get("edges", [])
        caption = caption_edges[0].get("node", {}).get("text", "") if caption_edges else ""
        ts = node.get("taken_at_timestamp")
        posted_at = None
        if ts:
            from datetime import datetime, timezone
            posted_at = datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
        posts.append({
            "external_id": shortcode,
            "description": caption[:500],
            "thumbnail_url": node.get("thumbnail_src") or node.get("display_url") or "",
            "post_url": f"https://www.instagram.com/p/{shortcode}/",
            "view_count":    (
                node.get("video_view_count")
                or node.get("video_play_count")
                or node.get("play_count")
                or 0
            ),
            "like_count":    (
                node.get("edge_liked_by", {}).get("count")
                or node.get("edge_media_preview_like", {}).get("count") or 0
            ),
            "comment_count": node.get("edge_media_to_comment", {}).get("count") or 0,
            "share_count":   0,
            "posted_at":     posted_at,
        })

    return {
        "display_name": display_name,
        "avatar_url":   avatar_url,
        "bio":          bio,
        "follower_count":  follower_count,
        "following_count": following_count,
        "like_count":  0,
        "post_count":  post_count,
        "_posts":      _merge_reels_views_into_posts(username, posts),
    }


def _fetch_instagram_playwright(username: str) -> dict:
    """Fallback: Playwright subprocess (requires manual login in browser)."""
    try:
        return _call_instagram_worker({"username": username})
    except ValueError as e:
        # Worker may return plain text errors without PROFILE_UNAVAILABLE prefix.
        # Normalize known "page unavailable / not found" phrases so views can
        # reliably set account.profile_unavailable.
        if _message_indicates_removed_instagram_profile(str(e)):
            raise_instagram_profile_unavailable(username)
        raise
