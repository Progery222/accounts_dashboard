"""Синхронный пайплайн Apify: стадии подряд, apply в БД до возврата."""
from __future__ import annotations

import logging

from django.utils import timezone

from accounts.apify_completion import mark_apify_run_detail_running
from accounts.models import ApifyRefreshJob, ApifyRefreshJobStatus, Platform

from . import client
from .config import actor_for_stage, poll_max_wait_sec
from .pipeline import (
    _build_input,
    _fail_job,
    _first_stage,
    _next_stage,
    _normalize_and_apply,
    _prepare_facebook_playcount,
    _save_stages,
    _stage_list,
)
from .pool import acquire_run_slot, release_run_slot

logger = logging.getLogger(__name__)


def _run_stage_blocking(job: ApifyRefreshJob, stage: str) -> bool:
    """
    Запустить стадию Apify и дождаться завершения.
    False — job переведён в FAILED/ABORTED.
    """
    job.refresh_from_db()
    if job.status in (
        ApifyRefreshJobStatus.SUCCEEDED,
        ApifyRefreshJobStatus.FAILED,
        ApifyRefreshJobStatus.ABORTED,
    ):
        return False

    if not acquire_run_slot(timeout=7200.0):
        _fail_job(job, "Нет свободного слота Apify (лимит параллельных run)")
        return False

    actor = actor_for_stage(job.platform, stage)
    run_id = ""
    try:
        run_input = _build_input(job, stage)
        run_data = client.start_run(actor, run_input)
        run_id = str(run_data["id"])
        dataset_id = str(run_data.get("defaultDatasetId") or "")
        stages = _stage_list(job)
        stages.append(
            {
                "stage": stage,
                "actor": actor,
                "run_id": run_id,
                "status": "RUNNING",
                "dataset_id": dataset_id,
            }
        )
        job = _save_stages(
            job,
            stages,
            status=ApifyRefreshJobStatus.RUNNING,
            apify_run_id=run_id,
            apify_actor_id=actor,
            apify_dataset_id=dataset_id,
            started_at=job.started_at or timezone.now(),
        )
        mark_apify_run_detail_running(job, stage=stage, actor=actor, run_id=run_id)

        meta = client.wait_for_run(
            run_id,
            max_wait_sec=poll_max_wait_sec(job.platform),
        )
    except Exception as exc:
        release_run_slot()
        logger.exception("apify.sync_stage_failed", extra={"job_id": job.pk, "stage": stage})
        _fail_job(job, str(exc))
        return False

    terminal = str(meta.get("status") or "")
    stages = _stage_list(job)
    stage_idx = -1
    for i, st in enumerate(stages):
        if str(st.get("run_id")) == run_id:
            stage_idx = i
            st["status"] = terminal
            st["usage"] = client.run_usage(meta)
            if not st.get("dataset_id"):
                st["dataset_id"] = meta.get("defaultDatasetId")
            break

    usage_extra = dict(job.run_detail_extra or {})
    usage_extra["last_usage"] = client.run_usage(meta)
    job.run_detail_extra = usage_extra
    job = _save_stages(job, stages)
    release_run_slot()

    if terminal != "SUCCEEDED":
        if stage == "profile" and job.platform in (Platform.FACEBOOK, Platform.INSTAGRAM):
            _fail_job(job, f"Apify {stage}: {terminal}")
        elif stage == "posts" and job.platform == Platform.INSTAGRAM:
            _fail_job(job, f"Apify posts: {terminal}")
        else:
            _fail_job(job, f"Apify run {terminal}")
        return False

    if stage_idx >= 0 and stage == "profile" and job.platform == Platform.FACEBOOK:
        ds = stages[stage_idx].get("dataset_id") or job.apify_dataset_id
        crowd_items = client.fetch_dataset_items(str(ds))
        job = _save_stages(job, stages)
        if not _prepare_facebook_playcount(job, crowd_items):
            try:
                _normalize_and_apply(job)
            except Exception as exc:
                _fail_job(job, str(exc))
            return job.status == ApifyRefreshJobStatus.SUCCEEDED

    return True


def run_job_pipeline_sync(job_id: int) -> ApifyRefreshJob:
    """Выполнить все стадии job в текущем потоке; по завершении данные в БД."""
    job = ApifyRefreshJob.objects.select_related("account").get(pk=job_id)
    if job.status not in (
        ApifyRefreshJobStatus.QUEUED,
        ApifyRefreshJobStatus.STARTING,
    ):
        return job

    ApifyRefreshJob.objects.filter(pk=job_id).update(status=ApifyRefreshJobStatus.STARTING)
    job.refresh_from_db()

    stage = _first_stage(job.platform)
    while stage:
        job.refresh_from_db()
        if job.status in (
            ApifyRefreshJobStatus.FAILED,
            ApifyRefreshJobStatus.ABORTED,
            ApifyRefreshJobStatus.SUCCEEDED,
        ):
            break
        if not _run_stage_blocking(job, stage):
            break
        job.refresh_from_db()
        if job.status == ApifyRefreshJobStatus.SUCCEEDED:
            break
        stage = _next_stage(job, stage)

    job.refresh_from_db()
    if job.status in (ApifyRefreshJobStatus.RUNNING, ApifyRefreshJobStatus.STARTING):
        try:
            _normalize_and_apply(job)
        except Exception as exc:
            logger.exception("apify.sync_apply_failed", extra={"job_id": job.pk})
            _fail_job(job, str(exc))

    return ApifyRefreshJob.objects.select_related("account").get(pk=job_id)
