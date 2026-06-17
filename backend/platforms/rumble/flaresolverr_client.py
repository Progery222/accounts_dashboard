"""FlareSolverr fallback for Rumble when Cloudflare blocks Playwright/httpx."""
from __future__ import annotations

import os
import sys
import threading
from contextlib import contextmanager
from typing import Iterator

import httpx

from platforms.rumble.parse import (
    about_urls,
    extract_posts,
    feed_urls,
    is_antibot_html,
    is_not_found_html,
    profile_from_html,
)

_DEFAULT_URL = "http://127.0.0.1:8191/v1"
_PROBE_TIMEOUT = 2.5
_REQUEST_TIMEOUT = 150.0
_FIRST_REQUEST_TIMEOUT_MS = 90_000
_FOLLOWUP_REQUEST_TIMEOUT_MS = 45_000

_shared_lock = threading.Lock()
_shared_session: _FlareSolverrSession | None = None


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


def _acquire_shared_session() -> _FlareSolverrSession:
    global _shared_session
    with _shared_lock:
        if _shared_session is None:
            _shared_session = _FlareSolverrSession()
            _shared_session.__enter__()
        return _shared_session


def flaresolverr_url() -> str:
    return (os.environ.get("FLARESOLVERR_URL") or _DEFAULT_URL).strip()


def flaresolverr_enabled() -> bool:
    flag = (os.environ.get("RUMBLE_FLARESOLVERR_ENABLED") or "true").strip().lower()
    return flag not in {"0", "false", "no", "off"}


def is_available() -> bool:
    if not flaresolverr_enabled():
        return False
    try:
        with httpx.Client(timeout=_PROBE_TIMEOUT) as client:
            r = client.post(
                flaresolverr_url(),
                json={"cmd": "sessions.list"},
            )
            data = r.json()
            return data.get("status") == "ok"
    except Exception:
        return False


def _parse_fs_response(r: httpx.Response) -> dict:
    try:
        data = r.json()
    except Exception as exc:
        raise RuntimeError(f"FlareSolverr: невалидный ответ ({r.status_code})") from exc
    if data.get("status") != "ok":
        raise RuntimeError(data.get("message") or "FlareSolverr error")
    return data


class _FlareSolverrSession:
    """Одна сессия FlareSolverr — challenge решается один раз, cookies переиспользуются."""

    def __init__(self) -> None:
        self._client = httpx.Client(timeout=_REQUEST_TIMEOUT)
        self._session_id: str | None = None
        self._challenge_solved = False

    def __enter__(self) -> _FlareSolverrSession:
        data = self._cmd({"cmd": "sessions.create"})
        self._session_id = data.get("session")
        if not self._session_id:
            raise RuntimeError("FlareSolverr: sessions.create не вернул session id")
        return self

    def __exit__(self, *_exc) -> None:
        if self._session_id:
            try:
                self._cmd({"cmd": "sessions.destroy", "session": self._session_id})
            except Exception:
                pass
        self._client.close()

    def _cmd(self, payload: dict) -> dict:
        r = self._client.post(flaresolverr_url(), json=payload)
        return _parse_fs_response(r)

    def fetch_html(self, url: str, *, max_timeout_ms: int | None = None) -> str:
        if not self._session_id:
            raise RuntimeError("FlareSolverr session не инициализирована")
        if max_timeout_ms is None:
            max_timeout_ms = (
                _FOLLOWUP_REQUEST_TIMEOUT_MS
                if self._challenge_solved
                else _FIRST_REQUEST_TIMEOUT_MS
            )
        data = self._cmd(
            {
                "cmd": "request.get",
                "url": url,
                "maxTimeout": max_timeout_ms,
                "session": self._session_id,
            }
        )
        html = (data.get("solution") or {}).get("response") or ""
        if not html:
            raise RuntimeError("FlareSolverr вернул пустой HTML")
        if is_antibot_html(html):
            raise RuntimeError("FlareSolverr: страница всё ещё за Cloudflare challenge")
        self._challenge_solved = True
        return html


@contextmanager
def _session() -> Iterator[_FlareSolverrSession]:
    with _FlareSolverrSession() as sess:
        yield sess


def fetch_profile(username: str) -> dict:
    # Повторное использование FS-сессии между разными @username ломает feed (0 постов).
    release_shared_session()

    about_html = ""
    feed_html = ""
    best_feed_posts = 0

    fs = _acquire_shared_session()
    try:
        # Сначала лента: после about FlareSolverr иногда отдаёт feed без rum-video-thumbnail.
        for url in feed_urls(username):
            try:
                html = fs.fetch_html(url)
            except Exception as exc:
                print(f"[rumble] FlareSolverr feed {url}: {exc}", file=sys.stderr)
                if _challenge_failure(exc):
                    release_shared_session()
                    raise
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
                html = fs.fetch_html(url)
            except Exception as exc:
                print(f"[rumble] FlareSolverr about {url}: {exc}", file=sys.stderr)
                if _challenge_failure(exc):
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
        raise ValueError(f"Rumble @{username} не найден (FlareSolverr)")

    payload = profile_from_html(
        username=username,
        about_html=about_html,
        feed_html=feed_html,
    )
    payload["_source"] = "flaresolverr"
    posts = payload.get("_posts") or []
    post_count = int(payload.get("post_count") or 0)
    partial_posts = bool(post_count) and len(posts) < post_count
    payload["_quality_flags"] = {
        "anti_bot_detected": True,
        "about_parsed": bool(about_html),
        "feed_parsed": bool(feed_html),
        "partial_posts": partial_posts,
        "flaresolverr": True,
    }
    if not posts and post_count > 0:
        payload["_posts_authoritative"] = False
    elif partial_posts:
        payload["_posts_authoritative"] = False
    return payload


def extract_has_posts(html: str) -> bool:
    from platforms.rumble.parse import extract_posts

    return bool(extract_posts(html))
