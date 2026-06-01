"""Постановка Apify refresh в очередь."""
from __future__ import annotations

import uuid
from typing import Any

from django.utils import timezone

from accounts.models import Account, ApifyRefreshJob, ApifyRefreshJobStatus, ApifyRefreshJobTrigger

from .config import apify_enabled, use_apify_for_platform
from .pipeline import process_queued_jobs, start_job_pipeline


def dispatch_apify_refresh(
    account: Account,
    *,
    trigger: str = ApifyRefreshJobTrigger.MANUAL,
    parent_batch_id: uuid.UUID | None = None,
) -> ApifyRefreshJob:
    if not apify_enabled():
        raise ValueError("Apify отключён (APIFY_ENABLED=0 или нет APIFY_TOKEN)")
    if not use_apify_for_platform(account.platform):
        raise ValueError(f"Для {account.platform} не выбран backend Apify")

    job = ApifyRefreshJob.objects.create(
        account=account,
        platform=account.platform,
        username_snapshot=account.username,
        status=ApifyRefreshJobStatus.QUEUED,
        trigger=trigger,
        parent_batch_id=parent_batch_id,
        apify_stages=[],
        started_at=timezone.now(),
    )
    start_job_pipeline(job.pk)
    process_queued_jobs()
    return job


def dispatch_apify_refresh_for_batch(
    account: Account,
    *,
    trigger: str,
    parent_batch_id: uuid.UUID,
    run_detail_patch: dict[str, Any] | None = None,
) -> ApifyRefreshJob:
    job = dispatch_apify_refresh(
        account,
        trigger=trigger,
        parent_batch_id=parent_batch_id,
    )
    if run_detail_patch:
        from accounts.apify_completion import _update_run_detail_item

        _update_run_detail_item(
            account.id,
            trigger=trigger,
            patch=run_detail_patch,
        )
    return job
