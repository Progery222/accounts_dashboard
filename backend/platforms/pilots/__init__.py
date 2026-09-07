"""Точечные пилоты Scrapling / Camoufox (опциональные зависимости, env-gate)."""
from __future__ import annotations

import os
import sys


def _flag(name: str, default: str = "false") -> bool:
    raw = (os.environ.get(name) or default).strip().lower()
    return raw in {"1", "true", "yes", "on"}


def scrapling_pilot_enabled(platform: str) -> bool:
    if not _flag("SCRAPLING_PILOT"):
        return False
    platforms = (os.environ.get("SCRAPLING_PILOT_PLATFORMS") or "rumble").strip().lower()
    if platforms in {"*", "all"}:
        return True
    return platform.lower() in {p.strip() for p in platforms.split(",") if p.strip()}


def camoufox_pilot_enabled(platform: str) -> bool:
    if not _flag("CAMOUFOX_PILOT"):
        return False
    platforms = (os.environ.get("CAMOUFOX_PILOT_PLATFORMS") or "rumble").strip().lower()
    if platforms in {"*", "all"}:
        return True
    return platform.lower() in {p.strip() for p in platforms.split(",") if p.strip()}


def fetch_html_scrapling(url: str, *, solve_cloudflare: bool = True) -> str:
    """
    StealthyFetcher (нужен: pip/poetry install 'scrapling[fetchers]' + scrapling install).
    """
    try:
        from scrapling.fetchers import StealthyFetcher
    except ImportError as exc:
        raise RuntimeError(
            "Scrapling не установлен. poetry add 'scrapling[fetchers]' && scrapling install"
        ) from exc

    print(f"[pilot:scrapling] fetch {url}", file=sys.stderr, flush=True)
    page = StealthyFetcher.fetch(
        url,
        headless=True,
        solve_cloudflare=solve_cloudflare,
    )
    html = getattr(page, "html_content", None) or getattr(page, "body", None) or str(page)
    if not html:
        raise RuntimeError("Scrapling вернул пустой HTML")
    return html


def fetch_html_camoufox(url: str) -> str:
    """
    Camoufox (нужен: poetry add camoufox && camoufox fetch).
    Тяжёлый Firefox-антидетект — только пилот.
    """
    try:
        from camoufox.sync_api import Camoufox
    except ImportError as exc:
        raise RuntimeError(
            "Camoufox не установлен. poetry add camoufox && python -m camoufox fetch"
        ) from exc

    print(f"[pilot:camoufox] fetch {url}", file=sys.stderr, flush=True)
    with Camoufox(headless=True) as browser:
        page = browser.new_page()
        page.goto(url, wait_until="domcontentloaded", timeout=90_000)
        html = page.content()
    if not html:
        raise RuntimeError("Camoufox вернул пустой HTML")
    return html
