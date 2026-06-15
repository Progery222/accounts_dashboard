"""Rumble profile fetch via Playwright worker_pool (как Threads/X)."""
from __future__ import annotations

import os
from pathlib import Path

from platforms.rumble.parse import normalize_username
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


def fetch_rumble_profile(username: str) -> dict:
    username = normalize_username(username)
    import sys

    from platforms.rumble import flaresolverr_client

    fs_tried = False
    fs_error: str | None = None

    if flaresolverr_client.is_available():
        fs_tried = True
        try:
            print(
                f"[rumble] FlareSolverr для @{username} (сессия, cookies переиспользуются)",
                file=sys.stderr,
            )
            return flaresolverr_client.fetch_profile(username)
        except Exception as exc:
            fs_error = str(exc)
            print(
                f"[rumble] FlareSolverr для @{username}: {exc}",
                file=sys.stderr,
            )
            if not playwright_fallback_enabled():
                raise ValueError(
                    f"Rumble @{username}: не удалось обновить. FlareSolverr: {fs_error}"
                ) from exc

    if not playwright_fallback_enabled():
        raise ValueError(
            f"Rumble @{username}: FlareSolverr недоступен. "
            "Запустите FlareSolverr (:8191) или RUMBLE_PLAYWRIGHT_FALLBACK=1."
        )

    try:
        return _run_worker(username)
    except Exception as worker_exc:
        print(
            f"[rumble] worker для @{username}: {worker_exc}",
            file=sys.stderr,
        )
        msg = str(worker_exc).lower()
        anti_bot = ("антибот" in msg) or ("challenge" in msg)

        if not fs_tried and flaresolverr_client.is_available():
            try:
                return flaresolverr_client.fetch_profile(username)
            except Exception as fs_exc:
                fs_error = str(fs_exc)
                print(
                    f"[rumble] FlareSolverr fallback для @{username}: {fs_exc}",
                    file=sys.stderr,
                )

        hint = ". Импортируйте cookies в Настройках → Rumble или запустите FlareSolverr."
        if fs_error:
            hint = f". FlareSolverr: {fs_error}"
        raise ValueError(
            f"Rumble @{username}: не удалось обновить"
            + (" (антибот)" if anti_bot else "")
            + hint
        ) from worker_exc
