"""Приоритет обновления аналитики аккаунтов над другими Playwright-задачами."""
from __future__ import annotations

import logging
import threading
from contextlib import contextmanager
from typing import Iterator

logger = logging.getLogger(__name__)

_GUARD = threading.Lock()
_ACTIVE_SESSIONS = 0

PRIORITY_BLOCK_MESSAGE = (
    "Операция прервана или недоступна: выполняется обновление аналитики аккаунтов."
)


def account_refresh_priority_active() -> bool:
    with _GUARD:
        return _ACTIVE_SESSIONS > 0


def interrupt_competing_playwright_for_account_refresh() -> None:
    """Закрыть Playwright-демоны и Chromium — освободить браузер для аналитики."""
    try:
        from platforms.worker_pool import shutdown_playwright_pool_aggressive

        shutdown_playwright_pool_aggressive(sleep_sec=0.35)
        logger.info("refresh_priority.interrupted_competing_playwright")
    except Exception as exc:
        logger.warning(
            "refresh_priority.interrupt_failed",
            extra={"error": str(exc)},
        )
    finally:
        # shutdown_all_workers() ставит force_stop, чтобы демоны не поднялись во время kill.
        # Сразу после прерывания снимаем флаг — иначе ручной refresh получает
        # «Остановлено пользователем» до запуска Facebook/Playwright worker.
        try:
            from platforms.worker_pool import clear_playwright_refresh_force_stop

            clear_playwright_refresh_force_stop()
        except Exception:
            pass


@contextmanager
def account_refresh_priority_session() -> Iterator[None]:
    """
    Пока активна сессия обновления аккаунтов:
    - при первом входе прерываются конкурирующие Playwright-задачи;
    - новые вызовы, проверяющие account_refresh_priority_active(), отклоняются.
    """
    global _ACTIVE_SESSIONS
    with _GUARD:
        _ACTIVE_SESSIONS += 1
        first = _ACTIVE_SESSIONS == 1
    if first:
        interrupt_competing_playwright_for_account_refresh()
    try:
        yield
    finally:
        with _GUARD:
            _ACTIVE_SESSIONS = max(0, _ACTIVE_SESSIONS - 1)
