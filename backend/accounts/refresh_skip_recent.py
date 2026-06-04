"""Пропуск недавно обновлённых аккаунтов в начале прогона (очередь в run_detail)."""
from __future__ import annotations

import datetime
from typing import Callable

from django.utils import timezone

from .models import Account, RefreshScheduleConfig
from .parallel_account_queue import ParallelAccountQueue


def schedule_skip_recent_cutoff(
    cfg: RefreshScheduleConfig | None = None,
) -> tuple[int, datetime.datetime | None]:
    """(часы из расписания, cutoff по updated_at) или (0, None) если пропуск выключен."""
    if cfg is None:
        cfg = RefreshScheduleConfig.get()
    try:
        cfg.refresh_from_db(fields=["skip_recent_hours"])
    except Exception:
        pass
    hours = max(0, int(getattr(cfg, "skip_recent_hours", 0) or 0))
    if hours <= 0:
        return 0, None
    return hours, timezone.now() - datetime.timedelta(hours=hours)


def should_skip_account_recent(
    account: Account,
    cutoff: datetime.datetime | None,
) -> bool:
    if cutoff is None:
        return False
    updated = getattr(account, "updated_at", None)
    return bool(updated and updated >= cutoff)


def skip_recent_detail(skip_recent_hours: int) -> str:
    return f"недавно обновлён (≤ {skip_recent_hours} ч)"


def initial_run_detail_item(
    account: Account,
    *,
    skip_recent_hours: int,
    cutoff: datetime.datetime | None,
    queued_detail: str = "",
) -> dict:
    base = {
        "account_id": account.id,
        "platform": account.platform,
        "username": account.username,
        "worker": None,
    }
    if should_skip_account_recent(account, cutoff):
        return {
            **base,
            "status": "skipped",
            "detail": skip_recent_detail(skip_recent_hours),
        }
    return {
        **base,
        "status": "queued",
        "detail": queued_detail or "в очереди",
    }


def build_initial_run_detail_items(
    accounts: list[Account],
    *,
    skip_recent_hours: int,
    cutoff: datetime.datetime | None,
    queued_detail: str = "",
) -> tuple[list[dict], int]:
    items = [
        initial_run_detail_item(
            a,
            skip_recent_hours=skip_recent_hours,
            cutoff=cutoff,
            queued_detail=queued_detail,
        )
        for a in accounts
    ]
    skip_count = sum(1 for it in items if it.get("status") == "skipped")
    return items, skip_count


def skip_recent_report_row(
    account: Account,
    *,
    skip_recent_hours: int,
    profile_name: Callable[[Account], str] | None = None,
) -> dict:
    """Строка CSV/отчёта для scheduled_refresh (как «пропущен» в воркере)."""
    pname = profile_name(account) if profile_name else ""
    fb = int(account.follower_count or 0)
    lb = int(account.like_count or 0)
    vb = int(account.view_count or 0)
    pb = int(account.post_count or 0)
    detail = skip_recent_detail(skip_recent_hours)
    return {
        "platform": account.platform,
        "username": account.username,
        "profile_name": pname,
        "status": "пропущен",
        "follower_before": fb,
        "follower_after": fb,
        "like_before": lb,
        "like_after": lb,
        "view_before": vb,
        "view_after": vb,
        "post_before": pb,
        "post_after": pb,
        "elapsed_sec": 0,
        "detail": detail,
    }


def apply_upfront_skip_recent(
    accounts: list[Account],
    *,
    cutoff: datetime.datetime | None,
    skip_recent_hours: int,
    account_queue: ParallelAccountQueue | None = None,
    report_by_index: list | None = None,
    profile_name: Callable[[Account], str] | None = None,
) -> int:
    """
    Пометить недавно обновлённые аккаунты как завершённые в очереди воркеров
    и (опционально) заполнить report_by_index для отчёта.
    Возвращает число пропущенных.
    """
    if cutoff is None:
        return 0
    skip_count = 0
    for idx, account in enumerate(accounts):
        if not should_skip_account_recent(account, cutoff):
            continue
        skip_count += 1
        if account_queue is not None:
            account_queue.mark_done_without_processing(idx)
        if report_by_index is not None and 0 <= idx < len(report_by_index):
            report_by_index[idx] = skip_recent_report_row(
                account,
                skip_recent_hours=skip_recent_hours,
                profile_name=profile_name,
            )
    return skip_count
