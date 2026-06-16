"""Согласованный прогресс автообновления: run_detail vs processed_accounts."""
from __future__ import annotations

import uuid
from typing import Any

from django.utils import timezone

from accounts.models import ApifyRefreshJob, ApifyRefreshJobTrigger, AutoRefreshState

_TERMINAL_STATUSES = frozenset({"done", "error", "skipped", "cancelled"})
_ACTIVE_ITEM_STATUSES = frozenset({"queued", "running"})
_RESTART_LAST_ERROR = "Автообновление было прервано перезапуском процесса."


def refresh_run_in_progress(state, *, source: str | None = None) -> bool:
    """Прогон ещё идёт: флаг is_running или в run_detail есть queued/running."""
    if getattr(state, "finished_at", None):
        return False
    if getattr(state, "is_running", False):
        return True
    src = (source or getattr(state, "source", None) or "").strip()
    if src not in ("bulk_refresh", "scheduler", "manual", "refresh_all"):
        return False
    rd = state.run_detail if isinstance(state.run_detail, dict) else {}
    items = rd.get("items") or []
    if not isinstance(items, list) or not items:
        return bool(getattr(state, "started_at", None))
    return any(
        str(it.get("status") or "").strip().lower() in _ACTIVE_ITEM_STATUSES
        for it in items
        if isinstance(it, dict)
    )


def progress_from_run_detail(
    run_detail: dict[str, Any] | None,
    *,
    db_total: int,
    db_done: int,
) -> tuple[int, int, int]:
    """
    (processed, total, progress_percent).
    Если в run_detail есть items — считаем по их статусам (источник правды для UI).
    """
    items: list[dict[str, Any]] = []
    if isinstance(run_detail, dict):
        raw = run_detail.get("items")
        if isinstance(raw, list):
            items = [x for x in raw if isinstance(x, dict)]
    if items:
        total = len(items)
        done = sum(
            1 for it in items if str(it.get("status") or "").strip().lower() in _TERMINAL_STATUSES
        )
    else:
        total = max(0, int(db_total or 0))
        done = max(0, int(db_done or 0))
    pct = 0 if total <= 0 else min(100, int(round((done / total) * 100)))
    return done, total, pct


def current_auto_refresh_apify_batch_id() -> uuid.UUID | None:
    state = AutoRefreshState.get()
    if not state.is_running:
        return None
    rd = state.run_detail if isinstance(state.run_detail, dict) else {}
    raw = rd.get("apify_batch_id")
    if not raw:
        return None
    try:
        return uuid.UUID(str(raw))
    except (TypeError, ValueError):
        return None


def touch_auto_refresh_run_alive_if_needed() -> None:
    """Пульс updated_at во время долгого Apify — иначе clear_stale может сбросить is_running."""
    try:
        st = AutoRefreshState.objects.filter(pk=1, is_running=True).only("pk").first()
        if st is None:
            return
        AutoRefreshState.objects.filter(pk=1, is_running=True).update(updated_at=timezone.now())
    except Exception:
        pass


def apify_job_applies_to_current_auto_refresh(job: ApifyRefreshJob) -> bool:
    """Не учитывать хвост Apify от прошлого прогона после нового batch."""
    if job.trigger not in (ApifyRefreshJobTrigger.BULK, ApifyRefreshJobTrigger.SCHEDULER):
        return True
    state = AutoRefreshState.get()
    if not state.is_running:
        return False
    current = current_auto_refresh_apify_batch_id()
    if current is not None:
        if job.parent_batch_id is None:
            return False
        return job.parent_batch_id == current
    rd = state.run_detail if isinstance(state.run_detail, dict) else {}
    items = rd.get("items") or []
    if items:
        aids = {int(x.get("account_id") or 0) for x in items if isinstance(x, dict)}
        return int(job.account_id or 0) in aids
    return True
