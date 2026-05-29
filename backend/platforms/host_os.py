"""Разделение поведения Playwright/деплоя: Windows (локальная разработка) vs Linux (сервер)."""
from __future__ import annotations

import os
import sys


def is_windows() -> bool:
    return sys.platform == "win32"


def is_linux() -> bool:
    return sys.platform.startswith("linux")


def mobilefarm_headed_display() -> str | None:
    """DISPLAY для видимых окон Playwright в Docker на GPU-сервере (compose .env)."""
    raw = (os.environ.get("MOBILEFARM_DISPLAY") or "").strip()
    return raw or None


def linux_prefers_headed_browser() -> bool:
    """
    Linux + задан MOBILEFARM_DISPLAY → headed refresh (окна на RDP/монитор).
    Иначе на сервере по умолчанию headless, если env не переопределили.
    """
    if not is_linux():
        return False
    if mobilefarm_headed_display():
        return True
    raw = (os.environ.get("MOBILEFARM_HEADED_BROWSER") or "").strip().lower()
    return raw in {"1", "true", "yes", "on"}
