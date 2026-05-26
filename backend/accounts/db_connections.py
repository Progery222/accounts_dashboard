"""Переподключение ORM после долгого Playwright/HTTP (потоки автообновления)."""
from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any, TypeVar

from django.db.utils import InterfaceError, OperationalError

T = TypeVar("T")


def ensure_fresh_db_connections() -> None:
    from django.db import close_old_connections, connection, connections

    close_old_connections()
    for conn in connections.all(initialized_only=True):
        conn.close_if_unusable_or_obsolete()
    try:
        connection.ensure_connection()
    except Exception:
        connection.close()
        connection.ensure_connection()


def release_db_for_long_task() -> None:
    """Закрыть все соединения потока перед минутным ожиданием worker/HTTP."""
    from django.db import close_old_connections, connections

    close_old_connections()
    for conn in connections.all(initialized_only=False):
        conn.close()


def stale_db_connection_error(exc: BaseException) -> bool:
    if isinstance(exc, InterfaceError):
        return True
    parts: list[str] = [str(exc).lower()]
    cause = getattr(exc, "__cause__", None)
    if cause is not None:
        parts.append(str(cause).lower())
    combined = " ".join(parts)
    markers = (
        "connection is closed",
        "connection already closed",
        "server closed the connection",
        "terminating connection",
        "ssl connection has been closed",
        "connection reset",
        "broken pipe",
        "could not receive data",
        "no connection to the server",
    )
    if any(m in combined for m in markers):
        return True
    return False


def run_with_db_reconnect(fn: Callable[[], T], *, attempts: int = 5) -> T:
    last: BaseException | None = None
    for attempt in range(max(1, attempts)):
        ensure_fresh_db_connections()
        try:
            return fn()
        except Exception as exc:
            last = exc
            if not stale_db_connection_error(exc) or attempt >= attempts - 1:
                raise
            time.sleep(0.25 + attempt * 0.35)
    assert last is not None
    raise last
