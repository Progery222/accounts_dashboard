"""
Facebook в массовом / автообновлении: один профиль, один браузер, одна вкладка.

- Воркер с номером 0 (в UI «воркер 1») — только Facebook (Playwright и Apify).
- Остальные воркеры не берут facebook из очереди.
- Все операции FB (съём + запись в БД / синхронный Apify) сериализуются одним lock.
- Демон facebook/worker.py поднимается один раз на FB-воркер; между аккаунтами окно не закрывается.
"""
from __future__ import annotations

import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from accounts.models import Account, Platform

FACEBOOK_PLATFORM = Platform.FACEBOOK
# В run_detail worker=0 — «воркер 1» только для Facebook.
FACEBOOK_DEDICATED_WORKER_SLOT = 0

_serial_lock = threading.Lock()
_batch_seen_ids: set[int] | None = None


def facebook_serial_lock() -> threading.Lock:
    """Один FB-аккаунт / один Apify job до полной записи в БД."""
    return _serial_lock


def begin_facebook_batch() -> None:
    global _batch_seen_ids
    _batch_seen_ids = set()


def end_facebook_batch() -> None:
    global _batch_seen_ids
    _batch_seen_ids = None


def batch_has_facebook(accounts: list[Account]) -> bool:
    return any(str(a.platform) == FACEBOOK_PLATFORM for a in accounts)


def platform_claim_filter(*, facebook_lane: bool) -> Callable[[str], bool]:
    if facebook_lane:
        return lambda p: str(p) == FACEBOOK_PLATFORM
    return lambda p: str(p) != FACEBOOK_PLATFORM


def try_mark_facebook_account_started(account_id: int) -> bool:
    """False — этот account_id уже обрабатывали в текущем прогоне."""
    if _batch_seen_ids is None:
        return True
    if account_id in _batch_seen_ids:
        return False
    _batch_seen_ids.add(account_id)
    return True


def allocate_worker_slot(
    *,
    facebook_lane: bool,
    thread_slot_map: dict[int, int],
    thread_slot_lock: threading.Lock,
) -> int:
    if facebook_lane:
        return FACEBOOK_DEDICATED_WORKER_SLOT
    tid = threading.get_ident()
    with thread_slot_lock:
        if tid not in thread_slot_map:
            used = set(thread_slot_map.values())
            n = 1
            while n in used:
                n += 1
            thread_slot_map[tid] = n
        return thread_slot_map[tid]


def executor_thread_counts(worker_count: int, *, has_facebook: bool) -> tuple[int, int]:
    """
    (потоки_facebook, потоки_остальные). Сумма = worker_count.
    FB всегда 1 поток; остальные платформы — worker_count - 1 (минимум 1 при наличии FB).
    """
    wc = max(1, int(worker_count))
    if not has_facebook:
        return (0, wc)
    return (1, max(1, wc - 1))


def submit_refresh_workers(
    executor: ThreadPoolExecutor,
    worker_fn: Callable[[bool], Any],
    *,
    worker_count: int,
    has_facebook: bool,
) -> list[Any]:
    fb_n, other_n = executor_thread_counts(worker_count, has_facebook=has_facebook)
    futures: list[Any] = []
    if fb_n:
        futures.append(executor.submit(worker_fn, True))
    for _ in range(other_n):
        futures.append(executor.submit(worker_fn, False))
    return futures


def filter_accounts_for_playwright_prewarm(accounts: list[Account]) -> list[Account]:
    """Общий prewarm не трогает Facebook — демон FB поднимает FB-воркер."""
    out = [a for a in accounts if str(a.platform) != FACEBOOK_PLATFORM]
    try:
        from platforms.rumble.scraper import skip_playwright_prewarm

        if skip_playwright_prewarm():
            out = [a for a in out if str(a.platform) != Platform.RUMBLE]
    except Exception:
        pass
    return out


def ensure_facebook_playwright_daemon_ready() -> None:
    """Один Chromium / facebook_from_state для всей FB-очереди прогона."""
    from platforms.worker_pool import ensure_worker, prepare_facebook_warm_session

    prepare_facebook_warm_session()
    worker_path = Path(__file__).resolve().parent.parent / "platforms" / "facebook" / "worker.py"
    ensure_worker(worker_path)


def run_facebook_serialized(fn: Callable[[], Any], *, platform: str) -> Any:
    if str(platform) != FACEBOOK_PLATFORM:
        return fn()
    with _serial_lock:
        return fn()
