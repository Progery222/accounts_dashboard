"""Rumble via FlareSolverr-совместимые solver’ы (Byparr / Solverr / FlareSolverr)."""
from __future__ import annotations

import os
import sys
import threading
from contextlib import contextmanager
from typing import Iterator

from platforms.challenge_solver import (
    ChallengeSolverSession,
    mark_solver_failed,
    pick_solver_url,
)
from platforms.rumble.parse import (
    about_urls,
    extract_posts,
    feed_urls,
    is_antibot_html,
    is_not_found_html,
    profile_from_html,
)

_shared_lock = threading.Lock()
_shared_session: ChallengeSolverSession | None = None


def _challenge_failure(exc: BaseException) -> bool:
    msg = str(exc).lower()
    return any(
        token in msg
        for token in (
            "challenge",
            "timeout after",
            "cloudflare",
            "antibot",
            "error solving",
            "страница всё ещё за cloudflare",
        )
    )


def release_shared_session() -> None:
    """Сбросить общую FS-сессию (конец batch или сбой challenge)."""
    global _shared_session
    with _shared_lock:
        sess = _shared_session
        _shared_session = None
    if sess is not None:
        try:
            sess.__exit__(None, None, None)
        except Exception:
            pass


def _acquire_shared_session() -> ChallengeSolverSession:
    global _shared_session
    with _shared_lock:
        if _shared_session is None:
            url = pick_solver_url()
            if not url:
                raise RuntimeError("Challenge solver недоступен")
            _shared_session = ChallengeSolverSession(url)
            _shared_session.__enter__()
        return _shared_session


def flaresolverr_url() -> str:
    return pick_solver_url() or (os.environ.get("FLARESOLVERR_URL") or "http://127.0.0.1:8191/v1").strip()


def flaresolverr_enabled() -> bool:
    flag = (os.environ.get("RUMBLE_FLARESOLVERR_ENABLED") or "true").strip().lower()
    return flag not in {"0", "false", "no", "off"}


def is_available() -> bool:
    if not flaresolverr_enabled():
        return False
    return pick_solver_url() is not None


# Обратная совместимость тестов / импортов.
_FlareSolverrSession = ChallengeSolverSession


def _parse_fs_response(r):
    from platforms.challenge_solver import parse_solver_response

    return parse_solver_response(r)


@contextmanager
def _session() -> Iterator[ChallengeSolverSession]:
    url = pick_solver_url()
    if not url:
        raise RuntimeError("Challenge solver недоступен")
    with ChallengeSolverSession(url) as sess:
        yield sess


def fetch_profile(username: str) -> dict:
    # Повторное использование FS-сессии между разными @username ломает feed (0 постов).
    release_shared_session()

    about_html = ""
    feed_html = ""
    best_feed_posts = 0
    solver_label = "challenge_solver"

    fs = _acquire_shared_session()
    solver_label = fs.base_url
    try:
        for url in feed_urls(username):
            try:
                html = fs.fetch_html(url, antibot_check=is_antibot_html)
            except Exception as exc:
                print(f"[rumble] solver feed {url}: {exc}", file=sys.stderr)
                if _challenge_failure(exc):
                    mark_solver_failed(fs.base_url)
                    release_shared_session()
                    # Попробовать следующий solver в цепочке один раз.
                    nxt = pick_solver_url(force_refresh=True)
                    if nxt and nxt != solver_label:
                        print(f"[rumble] переключение solver → {nxt}", file=sys.stderr)
                        fs = _acquire_shared_session()
                        solver_label = fs.base_url
                        try:
                            html = fs.fetch_html(url, antibot_check=is_antibot_html)
                        except Exception as exc2:
                            release_shared_session()
                            raise exc2 from exc
                    else:
                        raise
                else:
                    continue
            if is_not_found_html(html):
                continue
            posts_n = len(extract_posts(html))
            if posts_n > best_feed_posts or not feed_html:
                feed_html = html
                best_feed_posts = posts_n
            if posts_n > 0:
                break

        for url in about_urls(username):
            try:
                html = fs.fetch_html(url, antibot_check=is_antibot_html)
            except Exception as exc:
                print(f"[rumble] solver about {url}: {exc}", file=sys.stderr)
                if _challenge_failure(exc):
                    mark_solver_failed(fs.base_url)
                    release_shared_session()
                    raise
                continue
            if is_not_found_html(html):
                continue
            about_html = html
            break
    except Exception:
        raise

    if not about_html and not feed_html:
        raise ValueError(f"Rumble @{username} не найден (challenge solver)")

    payload = profile_from_html(
        username=username,
        about_html=about_html,
        feed_html=feed_html,
    )
    payload["_source"] = "flaresolverr"
    payload["_solver_url"] = solver_label
    posts = payload.get("_posts") or []
    post_count = int(payload.get("post_count") or 0)
    partial_posts = bool(post_count) and len(posts) < post_count
    payload["_quality_flags"] = {
        "anti_bot_detected": True,
        "about_parsed": bool(about_html),
        "feed_parsed": bool(feed_html),
        "partial_posts": partial_posts,
        "flaresolverr": True,
        "solver_url": solver_label,
    }
    if not posts and post_count > 0:
        payload["_posts_authoritative"] = False
    elif partial_posts:
        payload["_posts_authoritative"] = False
    return payload


def extract_has_posts(html: str) -> bool:
    from platforms.rumble.parse import extract_posts

    return bool(extract_posts(html))
