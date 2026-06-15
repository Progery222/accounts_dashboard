"""Фильтры для шумных HTTP-запросов в django.server."""
from __future__ import annotations

import logging


class SuppressNoisyPollingFilter(logging.Filter):
    """Не логировать частый GET-поллинг статуса фоновых обновлений."""

    _PATH_FRAGMENTS = (
        "GET /api/accounts/auto-refresh-status/",
        "GET /api/accounts/refresh-all-status/",
    )

    def filter(self, record: logging.LogRecord) -> bool:
        if record.name != "django.server":
            return True
        msg = record.getMessage()
        return not any(fragment in msg for fragment in self._PATH_FRAGMENTS)
