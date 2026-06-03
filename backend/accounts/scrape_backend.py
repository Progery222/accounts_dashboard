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


def apify_platforms_in_accounts(accounts: list[Account]) -> set[str]:
    return {str(a.platform) for a in accounts if should_use_apify_for_account(a)}


def scheduled_auto_refresh_worker_count(accounts: list[Account]) -> int:
    """
    Потоки для расписания / «Запустить сейчас»:

    - только Playwright → как bulk/refresh_all (_parallel_refresh_worker_count);
    - только Apify, одна платформа в пакете → 1;
    - только Apify, несколько платформ → параллельно (лимит APIFY_MAX_CONCURRENT_RUNS);
    - смесь Apify + Playwright → общий пул воркеров, Playwright параллельно, Apify по
      слотам платформ в ParallelAccountQueue (не блокируем весь прогон одним потоком).
    """
    if not accounts:
        return 1

    from django.conf import settings

    from accounts.views import _parallel_refresh_worker_count, _refresh_worker_count

    apify_platforms = apify_platforms_in_accounts(accounts)
    playwright_accounts = accounts_needing_playwright(accounts)

    if not apify_platforms:
        return _parallel_refresh_worker_count(list(accounts))

    if not playwright_accounts:
        if len(apify_platforms) <= 1:
            return 1
        apify_cap = max(1, int(getattr(settings, "APIFY_MAX_CONCURRENT_RUNS", 3) or 3))
        env_cap = _refresh_worker_count(account_count=len(accounts))
        parallel = _parallel_refresh_worker_count(
            [a for a in accounts if should_use_apify_for_account(a)],
        )
        return max(1, min(16, len(accounts), apify_cap, env_cap, parallel))

    return _parallel_refresh_worker_count(list(accounts))


def dispatch_apify_for_batch_account(
    account: Account,
    *,
    trigger: str,
    parent_batch_id: uuid.UUID,
) -> int:
    """Устаревший async-путь; для batch/auto используйте refresh_account_via_apify_sync."""
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


def refresh_account_via_apify_sync(
    account: Account,
    *,
    trigger: str,
    parent_batch_id: uuid.UUID,
) -> Account:
    """
    Синхронный Apify refresh для batch / автообновления:
    один job на аккаунт, все стадии подряд, запись в БД до возврата.
  """
    from django.utils import timezone

    from accounts.models import ApifyRefreshJob, ApifyRefreshJobStatus
    from platforms.apify.abort import abort_active_apify_jobs_for_account
    from platforms.apify.sync_pipeline import run_job_pipeline_sync

    if not apify_enabled():
        raise ValueError("Apify отключён (APIFY_ENABLED=0 или нет APIFY_TOKEN)")
    if not use_apify_for_platform(account.platform):
        raise ValueError(f"Для {account.platform} не выбран backend Apify")

    abort_active_apify_jobs_for_account(account.pk)

    patch: dict[str, Any] = {
        "backend": "apify",
        "status": "running",
        "detail": "Apify (синхронно)",
        "apify_stage": "queued",
        "apify_stages": [],
    }
    job = ApifyRefreshJob.objects.create(
        account=account,
        platform=account.platform,
        username_snapshot=account.username,
        status=ApifyRefreshJobStatus.QUEUED,
        trigger=trigger,
        parent_batch_id=parent_batch_id,
        apify_stages=[],
        run_detail_extra={"sync_inline": True},
        started_at=timezone.now(),
    )
    from accounts.apify_completion import _update_run_detail_item

    _update_run_detail_item(
        account.id,
        trigger=trigger,
        patch=patch,
    )
    run_job_pipeline_sync(job.pk)
    job.refresh_from_db()
    account.refresh_from_db()
    return account


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
