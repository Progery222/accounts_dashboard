"""Отмена активных Apify jobs (refresh cancel)."""
from __future__ import annotations

import logging

from django.utils import timezone

from accounts.models import ApifyRefreshJob, ApifyRefreshJobStatus

from . import client
from .pool import release_run_slot

logger = logging.getLogger(__name__)

_ACTIVE = (
    ApifyRefreshJobStatus.QUEUED,
    ApifyRefreshJobStatus.STARTING,
    ApifyRefreshJobStatus.RUNNING,
)


def abort_active_apify_jobs_for_account(account_id: int) -> int:
    """Отменить активные Apify jobs одного аккаунта (перед синхронным refresh)."""
    qs = ApifyRefreshJob.objects.filter(
        account_id=int(account_id),
        status__in=_ACTIVE,
    )
    count = 0
    for job in qs:
        run_id = (job.apify_run_id or "").strip()
        if run_id:
            try:
                client.abort_run(run_id)
            except Exception as exc:
                logger.warning("apify.abort_failed", extra={"run_id": run_id, "error": str(exc)})
        job.status = ApifyRefreshJobStatus.ABORTED
        job.finished_at = timezone.now()
        job.error_message = "Отменено перед новым запуском"
        job.save(update_fields=["status", "finished_at", "error_message", "updated_at"])
        release_run_slot()
        count += 1
    return count


def abort_active_apify_jobs(*, parent_batch_id=None) -> int:
    qs = ApifyRefreshJob.objects.filter(status__in=_ACTIVE)
    if parent_batch_id is not None:
        qs = qs.filter(parent_batch_id=parent_batch_id)
    count = 0
    for job in qs:
        run_id = (job.apify_run_id or "").strip()
        if run_id:
            try:
                client.abort_run(run_id)
            except Exception as exc:
                logger.warning("apify.abort_failed", extra={"run_id": run_id, "error": str(exc)})
        job.status = ApifyRefreshJobStatus.ABORTED
        job.finished_at = timezone.now()
        job.error_message = "Отменено пользователем"
        job.save(update_fields=["status", "finished_at", "error_message", "updated_at"])
        release_run_slot()
        count += 1
    return count
