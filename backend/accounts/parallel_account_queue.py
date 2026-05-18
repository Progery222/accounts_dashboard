"""Очередь аккаунтов для параллельного обновления: воркеры ищут по всему списку, а не только с головы."""
from __future__ import annotations

import threading
import time
from typing import Callable


class ParallelAccountQueue:
    """
    Раздаёт индексы аккаунтов воркерам с учётом лимита параллелизма по платформе.
    Если следующие в списке заняты (например, threads=1), берётся любой доступный дальше по очереди.
    """

    def __init__(self, total: int, platform_limits: dict[str, int]) -> None:
        self._total = max(0, int(total))
        self._limits = {str(k): max(1, int(v)) for k, v in (platform_limits or {}).items()}
        self._lock = threading.Lock()
        self._cond = threading.Condition(self._lock)
        self._completed: set[int] = set()
        self._claimed: set[int] = set()
        self._sems: dict[str, threading.BoundedSemaphore] = {
            p: threading.BoundedSemaphore(value=lim) for p, lim in self._limits.items()
        }
        self._cooldown_until: dict[str, float] = {p: 0.0 for p in self._limits}

    def _sem(self, platform: str) -> threading.BoundedSemaphore:
        p = str(platform)
        if p not in self._sems:
            lim = max(1, int(self._limits.get(p, 1)))
            self._sems[p] = threading.BoundedSemaphore(value=lim)
            self._cooldown_until.setdefault(p, 0.0)
        return self._sems[p]

    def platform_ready(self, platform: str) -> bool:
        p = str(platform)
        with self._lock:
            return self._cooldown_until.get(p, 0.0) <= time.monotonic()

    def set_platform_cooldown(self, platform: str, seconds: float) -> None:
        if seconds <= 0:
            return
        p = str(platform)
        until = time.monotonic() + float(seconds)
        with self._lock:
            self._cooldown_until[p] = max(self._cooldown_until.get(p, 0.0), until)
        with self._cond:
            self._cond.notify_all()

    def claim(
        self,
        get_platform: Callable[[int], str],
        *,
        stop_event: threading.Event | None = None,
        wait: bool = True,
    ) -> int | None:
        """Возвращает индекс аккаунта или None, если все обработаны / остановка."""
        while True:
            if stop_event is not None and stop_event.is_set():
                return None
            with self._cond:
                if len(self._completed) >= self._total:
                    return None
                now = time.monotonic()
                for idx in range(self._total):
                    if idx in self._completed or idx in self._claimed:
                        continue
                    platform = str(get_platform(idx))
                    if self._cooldown_until.get(platform, 0.0) > now:
                        continue
                    sem = self._sem(platform)
                    if sem.acquire(blocking=False):
                        self._claimed.add(idx)
                        return idx
                if len(self._completed) >= self._total:
                    return None
                if not wait:
                    return None
                self._cond.wait(timeout=0.2)

    def finish(self, idx: int, platform: str) -> None:
        p = str(platform)
        sem = None
        with self._cond:
            self._claimed.discard(idx)
            self._completed.add(idx)
            sem = self._sems.get(p)
        if sem is not None:
            sem.release()
        with self._cond:
            self._cond.notify_all()

    def abandon(self, idx: int, platform: str) -> None:
        """Освободить слот без отметки «обработан» (остановка до начала работы)."""
        p = str(platform)
        sem = None
        with self._cond:
            self._claimed.discard(idx)
            sem = self._sems.get(p)
        if sem is not None:
            sem.release()
        with self._cond:
            self._cond.notify_all()
