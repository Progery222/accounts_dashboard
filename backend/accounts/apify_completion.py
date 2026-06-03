"""Завершение Apify job: прогресс refresh_all / bulk / scheduler."""
from __future__ import annotations

import logging
from typing import Any

from django.utils import timezone

from accounts.models import (
    ApifyRefreshJob,
    ApifyRefreshJobStatus,
    ApifyRefreshJobTrigger,
    AutoRefreshState,
    RefreshAllState,
)

logger = logging.getLogger(__name__)


def _find_run_detail_item(run_detail: dict, account_id: int) -> dict | None:
    items = run_detail.get("items") or []
    for it in items:
        if int(it.get("account_id") or it.get("id") or 0) == account_id:
            return it
    return None


def _update_run_detail_item(
    account_id: int,
    *,
    trigger: str,
    patch: dict[str, Any],
) -> None:
    if trigger == ApifyRefreshJobTrigger.REFRESH_ALL:
        from accounts.views import _persist_refresh_all_run_item

        status = patch.pop("status", None)
        detail = patch.pop("detail", "")
        worker = patch.pop("worker", None)
        extra = {k: v for k, v in patch.items() if k not in ("status", "detail", "worker")}
        if extra:
            st = RefreshAllState.get()
            rd = dict(st.run_detail or {})
            it = _find_run_detail_item(rd, account_id)
            if it is not None:
                it.update(extra)
                rd["items"] = [
                    it if int(x.get("account_id") or x.get("id") or 0) == account_id else x
                    for x in (rd.get("items") or [])
                ]
                st.run_detail = rd
                st.save(update_fields=["run_detail", "updated_at"])
        if status is not None:
            _persist_refresh_all_run_item(
                account_id,
                status=status,
                worker=worker,
                detail=detail,
            )
        return

    if trigger in (ApifyRefreshJobTrigger.BULK, ApifyRefreshJobTrigger.SCHEDULER):
        state = AutoRefreshState.get()
        rd = dict(state.run_detail or {})
        items = [dict(x) for x in (rd.get("items") or [])]
        changed = False
        for it in items:
            aid = int(it.get("account_id") or 0)
            if aid != account_id:
                continue
            it.update(patch)
            changed = True
        if changed:
            rd["items"] = items
            state.run_detail = rd
            state.save(update_fields=["run_detail", "updated_at"])


def mark_apify_run_detail_running(job: ApifyRefreshJob, *, stage: str, actor: str, run_id: str) -> None:
    if job.trigger == ApifyRefreshJobTrigger.MANUAL:
        return
    patch = {
        "backend": "apify",
        "apify_job_id": job.pk,
        "apify_run_id": run_id,
        "apify_actor_id": actor,
        "apify_stage": f"{stage}_running",
        "apify_stages": list(job.apify_stages or []),
        "status": "running",
        "detail": f"Apify: {stage}",
    }
    _update_run_detail_item(job.account_id, trigger=job.trigger, patch=patch)


def on_apify_job_finished(
    job: ApifyRefreshJob,
    *,
    success: bool,
    detail: str = "",
    account_row: dict | None = None,
) -> None:
    """Увеличить processed_accounts и обновить run_detail после apply."""
    trigger = job.trigger
    account_id = job.account_id

    if trigger == ApifyRefreshJobTrigger.REFRESH_ALL:
        from accounts.views import _refresh_all_atomic_progress, _persist_refresh_all_run_item

        if success:
            _refresh_all_atomic_progress(failed=False)
            _persist_refresh_all_run_item(account_id, status="done", worker=None, detail="")
        else:
            _refresh_all_atomic_progress(failed=True, last_error=detail)
            _persist_refresh_all_run_item(account_id, status="error", worker=None, detail=detail)
        if account_row:
            _update_run_detail_item(account_id, trigger=trigger, patch=account_row)
        return

    if trigger in (ApifyRefreshJobTrigger.BULK, ApifyRefreshJobTrigger.SCHEDULER):
        from accounts.auto_refresh_progress import apify_job_applies_to_current_auto_refresh

        if not apify_job_applies_to_current_auto_refresh(job):
            logger.info(
                "apify.completion ignored stale job_id=%s batch=%s trigger=%s",
                job.pk,
                job.parent_batch_id,
                job.trigger,
            )
            return

        def _write() -> None:
            state = AutoRefreshState.get()
            state.processed_accounts += 1
            if success:
                state.success_accounts += 1
            else:
                state.failed_accounts += 1
                state.last_error = detail[:500]
            state.save(
                update_fields=[
                    "processed_accounts",
                    "success_accounts",
                    "failed_accounts",
                    "last_error",
                    "updated_at",
                ],
            )

        from accounts.db_connections import run_with_db_reconnect

        run_with_db_reconnect(_write)
        status_label = "done" if success else "error"
        _update_run_detail_item(
            account_id,
            trigger=trigger,
            patch={
                "status": status_label,
                "worker": None,
                "detail": detail,
                "backend": "apify",
                "apify_job_id": job.pk,
            },
        )


def count_active_apify_jobs() -> int:
    from accounts.models import ApifyRefreshJobStatus

    return ApifyRefreshJob.objects.filter(
        status__in=[
            ApifyRefreshJobStatus.QUEUED,
            ApifyRefreshJobStatus.STARTING,
            ApifyRefreshJobStatus.RUNNING,
        ],
    ).count()
