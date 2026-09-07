"""
FlareSolverr-совместимые challenge-solver’ы (Byparr / Solverr / FlareSolverr).

Один и тот же POST /v1 API. Цепочка URL (первый доступный выигрывает):
  CHALLENGE_SOLVER_URLS=http://127.0.0.1:8192/v1,http://127.0.0.1:8193/v1,http://127.0.0.1:8191/v1
или по отдельности:
  BYPARR_URL / SOLVERR_URL / FLARESOLVERR_URL
"""
from __future__ import annotations

import os
import sys
import threading
from typing import Callable

import httpx

_DEFAULT_FLARE = "http://127.0.0.1:8191/v1"
_PROBE_TIMEOUT = 2.5
_REQUEST_TIMEOUT = 150.0

_url_lock = threading.Lock()
_cached_url: str | None = None
_cached_dead: set[str] = set()


def _split_urls(raw: str) -> list[str]:
    return [u.strip() for u in (raw or "").split(",") if u.strip()]


def challenge_solver_urls() -> list[str]:
    explicit = _split_urls(os.environ.get("CHALLENGE_SOLVER_URLS") or "")
    if explicit:
        return _dedupe(explicit)

    ordered: list[str] = []
    for key in ("BYPARR_URL", "SOLVERR_URL", "FLARESOLVERR_URL"):
        val = (os.environ.get(key) or "").strip()
        if val:
            ordered.append(val)
    if not ordered:
        ordered.append((os.environ.get("FLARESOLVERR_URL") or _DEFAULT_FLARE).strip())
    return _dedupe(ordered)


def _dedupe(urls: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for u in urls:
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out


def reset_solver_cache() -> None:
    global _cached_url
    with _url_lock:
        _cached_url = None
        _cached_dead.clear()


def _probe_url(url: str) -> bool:
    try:
        with httpx.Client(timeout=_PROBE_TIMEOUT) as client:
            r = client.post(url, json={"cmd": "sessions.list"})
            data = r.json()
            if data.get("status") == "ok":
                return True
            # Byparr иногда отвечает иначе на sessions.list — пробуем пустой request недопустим,
            # но 200 + JSON уже сигнал живости.
            if r.status_code < 500 and isinstance(data, dict):
                # Некоторые форки без sessions.list всё равно живы на /v1.
                msg = str(data.get("message") or "").lower()
                if "unknown" in msg or "cmd" in msg or data.get("status") == "error":
                    return True
    except Exception:
        return False
    return False


def pick_solver_url(*, force_refresh: bool = False) -> str | None:
    global _cached_url
    with _url_lock:
        if not force_refresh and _cached_url and _cached_url not in _cached_dead:
            return _cached_url
        for url in challenge_solver_urls():
            if url in _cached_dead:
                continue
            if _probe_url(url):
                _cached_url = url
                print(f"[challenge_solver] using {url}", file=sys.stderr, flush=True)
                return url
            _cached_dead.add(url)
            print(f"[challenge_solver] недоступен: {url}", file=sys.stderr, flush=True)
        _cached_url = None
        return None


def mark_solver_failed(url: str) -> None:
    global _cached_url
    with _url_lock:
        _cached_dead.add(url)
        if _cached_url == url:
            _cached_url = None


def parse_solver_response(r: httpx.Response) -> dict:
    try:
        data = r.json()
    except Exception as exc:
        raise RuntimeError(f"Challenge solver: невалидный ответ ({r.status_code})") from exc
    if data.get("status") != "ok":
        raise RuntimeError(data.get("message") or "Challenge solver error")
    return data


class ChallengeSolverSession:
    """
    Сессия FlareSolverr-API. Если sessions.create не поддерживается (Byparr),
    ходим request.get без session id.
    """

    def __init__(self, base_url: str | None = None) -> None:
        self.base_url = (base_url or pick_solver_url() or "").strip()
        if not self.base_url:
            raise RuntimeError("Challenge solver недоступен (Byparr/Solverr/FlareSolverr)")
        self._client = httpx.Client(timeout=_REQUEST_TIMEOUT)
        self._session_id: str | None = None
        self._challenge_solved = False
        self.supports_sessions = False

    def __enter__(self) -> ChallengeSolverSession:
        try:
            data = self._cmd({"cmd": "sessions.create"})
            sid = data.get("session")
            if sid:
                self._session_id = sid
                self.supports_sessions = True
        except Exception as exc:
            print(
                f"[challenge_solver] sessions.create недоступен на {self.base_url}: {exc} "
                "— request.get без session",
                file=sys.stderr,
            )
            self._session_id = None
            self.supports_sessions = False
        return self

    def __exit__(self, *_exc) -> None:
        if self._session_id:
            try:
                self._cmd({"cmd": "sessions.destroy", "session": self._session_id})
            except Exception:
                pass
        self._client.close()

    def _cmd(self, payload: dict) -> dict:
        r = self._client.post(self.base_url, json=payload)
        return parse_solver_response(r)

    def fetch_html(
        self,
        url: str,
        *,
        max_timeout_ms: int | None = None,
        antibot_check: Callable[[str], bool] | None = None,
    ) -> str:
        if max_timeout_ms is None:
            max_timeout_ms = 45_000 if self._challenge_solved else 90_000
        payload: dict = {
            "cmd": "request.get",
            "url": url,
            "maxTimeout": max_timeout_ms,
        }
        # Byparr docs: max_timeout в секундах — дублируем для совместимости.
        payload["max_timeout"] = max(1, int(max_timeout_ms / 1000))
        if self._session_id:
            payload["session"] = self._session_id
        data = self._cmd(payload)
        html = (data.get("solution") or {}).get("response") or ""
        if not html:
            raise RuntimeError("Challenge solver вернул пустой HTML")
        if antibot_check and antibot_check(html):
            raise RuntimeError("Challenge solver: страница всё ещё за Cloudflare challenge")
        self._challenge_solved = True
        return html
