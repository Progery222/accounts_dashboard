"""Фоновый polling Apify run (если webhook недоступен)."""
from __future__ import annotations

import logging
import os
import sys
import threading
import time

from django.conf import settings

logger = logging.getLogger(__name__)

_poller_thread: threading.Thread | None = None
_stop = threading.Event()


def _poll_loop() -> None:
    from .pipeline import poll_running_jobs, process_queued_jobs

    interval = max(5, int(getattr(settings, "APIFY_POLL_INTERVAL_SEC", 15) or 15))
    while not _stop.is_set():
        try:
            process_queued_jobs()
            poll_running_jobs()
        except Exception as exc:
            logger.warning("apify.poller_tick_failed", exc_info=exc)
        _stop.wait(interval)


def start_apify_poller() -> None:
    global _poller_thread
    from .config import apify_enabled

    if not apify_enabled():
        return
    if _poller_thread and _poller_thread.is_alive():
        return
    _stop.clear()
    _poller_thread = threading.Thread(target=_poll_loop, daemon=True, name="apify-poller")
    _poller_thread.start()
    print("[apify] poller started", file=sys.stderr, flush=True)


def stop_apify_poller() -> None:
    _stop.set()
