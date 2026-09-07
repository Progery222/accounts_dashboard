"""Rumble profile fetch: HTTP → challenge solvers → pilots → optional Playwright."""
from __future__ import annotations

import os
import sys
from pathlib import Path

from platforms.rumble.parse import (
    about_urls,
    feed_urls,
    is_antibot_html,
    is_not_found_html,
    normalize_username,
    profile_from_html,
)
from platforms.worker_pool import call_worker

_WORKER = Path(__file__).parent / "worker.py"


def playwright_fallback_enabled() -> bool:
    """
    Открывать Playwright при сбое FlareSolverr.
    По умолчанию false — только FS; окно браузера не нужно.
    """
    raw = (os.environ.get("RUMBLE_PLAYWRIGHT_FALLBACK") or "0").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def skip_playwright_prewarm() -> bool:
    """Не поднимать демон Rumble, пока не включён явный Playwright-fallback."""
    return not playwright_fallback_enabled()


def release_batch_resources() -> None:
    """Конец batch / сброс: FS-сессия и демон Playwright (если был)."""
    from platforms.rumble import flaresolverr_client

    flaresolverr_client.release_shared_session()
    if skip_playwright_prewarm():
        try:
            from platforms.worker_pool import shutdown_worker

            shutdown_worker(_WORKER)
        except Exception:
            pass


def _run_worker(username: str) -> dict:
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
        {
            "about_parsed": False,
            "feed_parsed": bool(data.get("_posts")),
            "partial_posts": not bool(data.get("_posts")),
        },
    )
    return data


def _fetch_via_pilot(username: str, *, engine: str) -> dict:
    from platforms.pilots import fetch_html_camoufox, fetch_html_scrapling

    fetch = fetch_html_scrapling if engine == "scrapling" else fetch_html_camoufox
    about_html = ""
    feed_html = ""
    for url in feed_urls(username):
        try:
            html = fetch(url)
        except Exception as exc:
            print(f"[rumble] {engine} feed {url}: {exc}", file=sys.stderr)
            continue
        if is_not_found_html(html) or is_antibot_html(html):
            continue
        feed_html = html
        break
    for url in about_urls(username):
        try:
            html = fetch(url)
        except Exception as exc:
            print(f"[rumble] {engine} about {url}: {exc}", file=sys.stderr)
            continue
        if is_not_found_html(html) or is_antibot_html(html):
            continue
        about_html = html
        break
    if not about_html and not feed_html:
        raise RuntimeError(f"Rumble @{username}: {engine} pilot пусто")
    payload = profile_from_html(username=username, about_html=about_html, feed_html=feed_html)
    payload["_source"] = engine
    payload["_quality_flags"] = {
        "anti_bot_detected": False,
        "about_parsed": bool(about_html),
        "feed_parsed": bool(feed_html),
        "partial_posts": False,
        engine: True,
    }
    return payload


def fetch_rumble_profile(username: str) -> dict:
    username = normalize_username(username)
    errors: list[str] = []

    # 1) HTTP-first (curl_cffi)
    try:
        from platforms.rumble.http_direct import fetch_profile_http, http_direct_enabled

        if http_direct_enabled():
            try:
                return fetch_profile_http(username)
            except Exception as exc:
                errors.append(f"http: {exc}")
                print(f"[rumble] HTTP-direct @{username}: {exc}", file=sys.stderr)
    except Exception as exc:
        errors.append(f"http_import: {exc}")

    # 2) Byparr / Solverr / FlareSolverr
    from platforms.rumble import flaresolverr_client

    fs_tried = False
    if flaresolverr_client.is_available():
        fs_tried = True
        try:
            print(
                f"[rumble] challenge-solver для @{username}",
                file=sys.stderr,
            )
            return flaresolverr_client.fetch_profile(username)
        except Exception as exc:
            errors.append(f"solver: {exc}")
            print(f"[rumble] challenge-solver @{username}: {exc}", file=sys.stderr)

    # 3) Точечные пилоты (опционально)
    try:
        from platforms.pilots import camoufox_pilot_enabled, scrapling_pilot_enabled

        if scrapling_pilot_enabled("rumble"):
            try:
                return _fetch_via_pilot(username, engine="scrapling")
            except Exception as exc:
                errors.append(f"scrapling: {exc}")
                print(f"[rumble] scrapling pilot @{username}: {exc}", file=sys.stderr)
        if camoufox_pilot_enabled("rumble"):
            try:
                return _fetch_via_pilot(username, engine="camoufox")
            except Exception as exc:
                errors.append(f"camoufox: {exc}")
                print(f"[rumble] camoufox pilot @{username}: {exc}", file=sys.stderr)
    except Exception as exc:
        errors.append(f"pilots: {exc}")

    # 4) Playwright только по флагу
    if not playwright_fallback_enabled():
        detail = "; ".join(errors) if errors else "solver недоступен"
        raise ValueError(
            f"Rumble @{username}: не удалось обновить ({detail}). "
            "Поднимите Byparr/Solverr/FlareSolverr, либо RUMBLE_PLAYWRIGHT_FALLBACK=1, "
            "либо SCRAPLING_PILOT=1 / CAMOUFOX_PILOT=1."
        )

    try:
        return _run_worker(username)
    except Exception as worker_exc:
        print(f"[rumble] worker для @{username}: {worker_exc}", file=sys.stderr)
        msg = str(worker_exc).lower()
        anti_bot = ("антибот" in msg) or ("challenge" in msg)

        if not fs_tried and flaresolverr_client.is_available():
            try:
                return flaresolverr_client.fetch_profile(username)
            except Exception as fs_exc:
                errors.append(f"solver_late: {fs_exc}")
                print(f"[rumble] solver late @{username}: {fs_exc}", file=sys.stderr)

        hint = "; ".join(errors[-3:]) if errors else str(worker_exc)
        raise ValueError(
            f"Rumble @{username}: не удалось обновить"
            + (" (антибот)" if anti_bot else "")
            + f". {hint}"
        ) from worker_exc
