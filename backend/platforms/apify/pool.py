"""Семафор одновременных Apify run (APIFY_MAX_CONCURRENT_RUNS)."""
from __future__ import annotations

import logging
import threading

from django.conf import settings

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_slots_in_use = 0
_max_slots = max(1, int(getattr(settings, "APIFY_MAX_CONCURRENT_RUNS", 3) or 3))
_slot_cond = threading.Condition(_lock)


def max_concurrent_runs() -> int:
    return _max_slots


def active_run_count() -> int:
    with _lock:
        return _slots_in_use


def acquire_run_slot(*, timeout: float | None = 3600.0) -> bool:
    global _slots_in_use
    with _slot_cond:
        deadline = None
        if timeout is not None:
            import time

            deadline = time.monotonic() + timeout
        while _slots_in_use >= _max_slots:
            if deadline is not None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                _slot_cond.wait(timeout=remaining)
            else:
                _slot_cond.wait()
        _slots_in_use += 1
        return True


def release_run_slot() -> None:
    global _slots_in_use
    with _slot_cond:
        if _slots_in_use > 0:
            _slots_in_use -= 1
        _slot_cond.notify_all()
