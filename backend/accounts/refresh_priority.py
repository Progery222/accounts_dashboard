"""Приоритет обновления аналитики аккаунтов над съёмом аудитории (subs)."""
from __future__ import annotations

import logging
import threading
from contextlib import contextmanager
from typing import Iterator

logger = logging.getLogger(__name__)

_GUARD = threading.Lock()
_ACTIVE_SESSIONS = 0

PRIORITY_BLOCK_MESSAGE = (
    "Съём аудитории прерван или недоступен: выполняется обновление аналитики аккаунтов."
)


def account_refresh_priority_active() -> bool:
    with _GUARD:
        return _ACTIVE_SESSIONS > 0


def interrupt_audience_scrape_for_account_refresh() -> None:
    """Закрыть Playwright-демоны и Chromium — освободить браузер для аналитики."""
    try:
        from platforms.worker_pool import shutdown_playwright_pool_aggressive

        shutdown_playwright_pool_aggressive(sleep_sec=0.35)
        logger.info("refresh_priority.interrupted_audience_scrape")
    except Exception as exc:
        logger.warning(
            "refresh_priority.interrupt_failed",
            extra={"error": str(exc)},
        )


@contextmanager
def account_refresh_priority_session() -> Iterator[None]:
    """
    Пока активна сессия обновления аккаунтов:
    - при первом входе прерывается текущий съём подписчиков;
    - новые вызовы fetch_audience_payload отклоняются.
    """
    global _ACTIVE_SESSIONS
    with _GUARD:
        _ACTIVE_SESSIONS += 1
        first = _ACTIVE_SESSIONS == 1
    if first:
        interrupt_audience_scrape_for_account_refresh()
    try:
        yield
    finally:
        with _GUARD:
            _ACTIVE_SESSIONS = max(0, _ACTIVE_SESSIONS - 1)
