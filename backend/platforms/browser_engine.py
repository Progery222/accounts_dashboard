"""
Единая точка выбора движка браузера для воркеров.

По умолчанию — Patchright (drop-in к Playwright Chromium, stealth-патчи).
Переключение: BROWSER_ENGINE=patchright|playwright
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

_ENGINE: str | None = None
_async_factory = None
_sync_factory = None


def browser_engine_name() -> str:
    raw = (os.environ.get("BROWSER_ENGINE") or "patchright").strip().lower()
    if raw in {"playwright", "pw", "stock"}:
        return "playwright"
    return "patchright"


def _default_patchright_browsers_path() -> Path | None:
    local = os.environ.get("LOCALAPPDATA") or os.environ.get("HOME") or ""
    if not local:
        return None
    # Patchright кладёт бинарники рядом с ms-playwright (свой driver + chromium).
    candidates = [
        Path(local) / "ms-playwright",
        Path(local) / "Local" / "ms-playwright",
    ]
    for c in candidates:
        if c.is_dir():
            return c
    # Ещё не ставили — всё равно укажем стандартный каталог под Windows.
    if os.name == "nt" and os.environ.get("LOCALAPPDATA"):
        return Path(os.environ["LOCALAPPDATA"]) / "ms-playwright"
    if os.environ.get("HOME"):
        return Path(os.environ["HOME"]) / ".cache" / "ms-playwright"
    return None


def normalize_browser_engines_env(
    env: dict[str, str] | None = None,
    *,
    mutate_os_environ: bool = False,
) -> dict[str, str | None]:
    """
    Нормализует PLAYWRIGHT_BROWSERS_PATH / PATCHRIGHT_BROWSERS_PATH.
    Для Patchright предпочитаем PATCHRIGHT_*; stock Playwright — PLAYWRIGHT_*.
    """
    from platforms.worker_utils import normalize_playwright_browsers_env

    store = os.environ if mutate_os_environ else (env if env is not None else os.environ)
    engine = browser_engine_name()
    if "BROWSER_ENGINE" not in store:
        store["BROWSER_ENGINE"] = engine

    pw_path = normalize_playwright_browsers_env(store if not mutate_os_environ else None, mutate_os_environ=mutate_os_environ)

    pr_raw = (store.get("PATCHRIGHT_BROWSERS_PATH") or "").strip()
    pr_path: str | None = None
    if pr_raw:
        pr_path = str(Path(pr_raw).expanduser().resolve())
    else:
        # Не подмешиваем чужой sandbox PLAYWRIGHT path в Patchright — свои бинарники.
        default_pr = _default_patchright_browsers_path()
        if default_pr is not None:
            pr_path = str(default_pr)
    if pr_path:
        store["PATCHRIGHT_BROWSERS_PATH"] = pr_path

    return {
        "BROWSER_ENGINE": engine,
        "PLAYWRIGHT_BROWSERS_PATH": pw_path,
        "PATCHRIGHT_BROWSERS_PATH": pr_path,
    }


def _load() -> None:
    global _ENGINE, _async_factory, _sync_factory
    if _ENGINE is not None:
        return

    name = browser_engine_name()
    if name == "patchright":
        try:
            from patchright.async_api import async_playwright as _ap
            from patchright.sync_api import sync_playwright as _sp

            _async_factory = _ap
            _sync_factory = _sp
            _ENGINE = "patchright"
        except ImportError as exc:
            print(
                f"[browser_engine] patchright недоступен ({exc}), fallback → playwright",
                file=sys.stderr,
                flush=True,
            )
            name = "playwright"

    if name == "playwright":
        from playwright.async_api import async_playwright as _ap
        from playwright.sync_api import sync_playwright as _sp

        _async_factory = _ap
        _sync_factory = _sp
        _ENGINE = "playwright"

    print(f"[browser_engine] engine={_ENGINE}", file=sys.stderr, flush=True)


def async_playwright(*args, **kwargs):
    """Тот же контракт, что у playwright/patchright: async with async_playwright() as pw."""
    _load()
    assert _async_factory is not None
    return _async_factory(*args, **kwargs)


def sync_playwright(*args, **kwargs):
    _load()
    assert _sync_factory is not None
    return _sync_factory(*args, **kwargs)


def active_engine() -> str:
    """Имя загруженного движка (после первого вызова async/sync_playwright)."""
    _load()
    assert _ENGINE is not None
    return _ENGINE
