"""Хелперы выбора backend сбора (Playwright vs Apify)."""
from __future__ import annotations

import uuid
from typing import Any

from accounts.models import Account, ScrapeBackendChoice, ScrapeBackendConfig

from platforms.apify.config import apify_enabled, use_apify_for_platform


def should_use_apify_for_account(account: Account) -> bool:
    return use_apify_for_platform(account.platform)


def facebook_playwright_warm_needed(accounts: list[Account]) -> bool:
    cfg = ScrapeBackendConfig.get()
    if cfg.facebook_backend == ScrapeBackendChoice.APIFY:
        return False
    from accounts.models import Platform

    return any(getattr(a, "platform", None) == Platform.FACEBOOK for a in accounts)


def accounts_needing_playwright(accounts: list[Account]) -> list[Account]:
    return [a for a in accounts if not should_use_apify_for_account(a)]


def dispatch_apify_for_batch_account(
    account: Account,
    *,
    trigger: str,
    parent_batch_id: uuid.UUID,
) -> int:
    from platforms.apify.dispatch import dispatch_apify_refresh_for_batch

    patch: dict[str, Any] = {
        "backend": "apify",
        "status": "running",
        "detail": "В очереди Apify",
        "apify_stage": "queued",
        "apify_stages": [],
    }
    job = dispatch_apify_refresh_for_batch(
        account,
        trigger=trigger,
        parent_batch_id=parent_batch_id,
        run_detail_patch=patch,
    )
    return job.pk


def apify_run_detail_patch_for_job(job) -> dict[str, Any]:
    label = "Сбор Apify…"
    if job.status == "queued":
        label = "В очереди Apify"
    return {
        "backend": "apify",
        "apify_job_id": job.pk,
        "apify_run_id": job.apify_run_id or None,
        "apify_actor_id": job.apify_actor_id or "",
        "apify_stages": list(job.apify_stages or []),
        "refresh_pipeline_label": label,
    }
