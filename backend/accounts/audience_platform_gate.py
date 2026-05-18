"""Глобальный лимит: один активный съём аудитории на площадку в процессе Django."""
from __future__ import annotations

import threading
from contextlib import contextmanager
from typing import Iterator

_GATE_GUARD = threading.Lock()
_PLATFORM_SEMS: dict[str, threading.BoundedSemaphore] = {}


def _normalize_platform_key(platform: str) -> str:
    return str(platform or "").strip().lower() or "unknown"


def _sem_for_platform(platform: str) -> threading.BoundedSemaphore:
    key = _normalize_platform_key(platform)
    with _GATE_GUARD:
        sem = _PLATFORM_SEMS.get(key)
        if sem is None:
            sem = threading.BoundedSemaphore(1)
            _PLATFORM_SEMS[key] = sem
        return sem


@contextmanager
def audience_platform_slot(platform: str) -> Iterator[None]:
    """Не более одного съёма аудитории на площадку в процессе Django (subs шлёт много POST)."""
    sem = _sem_for_platform(platform)
    sem.acquire()
    try:
        yield
    finally:
        sem.release()
