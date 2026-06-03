"""Блокировка async-poller во время sync-batch (scheduled / bulk / refresh_all)."""
from __future__ import annotations

import logging
import threading
import uuid
from contextlib import contextmanager
from typing import Iterator

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_active_batch_id: uuid.UUID | None = None


def get_active_sync_batch_id() -> uuid.UUID | None:
    with _lock:
        return _active_batch_id


def is_sync_batch_active() -> bool:
    return get_active_sync_batch_id() is not None


def enter_sync_apify_batch(batch_id: uuid.UUID) -> None:
    global _active_batch_id
    with _lock:
        if _active_batch_id is not None:
            logger.warning(
                "apify.sync_batch_already_active",
                extra={"current": str(_active_batch_id), "new": str(batch_id)},
            )
            return
        _active_batch_id = batch_id


def leave_sync_apify_batch() -> None:
    global _active_batch_id
    with _lock:
        _active_batch_id = None


@contextmanager
def sync_apify_batch(batch_id: uuid.UUID) -> Iterator[None]:
    enter_sync_apify_batch(batch_id)
    try:
        yield
    finally:
        leave_sync_apify_batch()


def is_sync_inline_job(job) -> bool:
    extra = job.run_detail_extra if isinstance(getattr(job, "run_detail_extra", None), dict) else {}
    return bool(extra.get("sync_inline"))


def job_belongs_to_active_sync_batch(job) -> bool:
    active = get_active_sync_batch_id()
    if active is None:
        return False
    return getattr(job, "parent_batch_id", None) == active


def poller_should_ignore_job(job) -> bool:
    """Не обрабатывать job в async-poller (sync-batch или sync_inline)."""
    if is_sync_inline_job(job):
        return True
    return job_belongs_to_active_sync_batch(job)
