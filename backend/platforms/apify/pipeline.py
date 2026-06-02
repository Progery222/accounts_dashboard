"""Оркестрация multi-stage Apify run и завершение job."""
from __future__ import annotations

import logging
import re
import threading
from typing import Any

from django.conf import settings
from django.utils import timezone

from accounts.apify_completion import mark_apify_run_detail_running, on_apify_job_finished
from accounts.models import (
    Account,
    ApifyRefreshJob,
    ApifyRefreshJobStatus,
    ApifyRefreshJobTrigger,
    Platform,
    Post,
)

from . import client
from .apply import apply_normalized_refresh
from .config import actor_for_stage, poll_max_wait_sec
from .normalizers import (
    normalize_facebook,
    normalize_instagram,
    normalize_reddit,
    normalize_rumble,
    normalize_tiktok,
    normalize_youtube,
)
from .pool import acquire_run_slot, release_run_slot

logger = logging.getLogger(__name__)

_finish_lock = threading.Lock()
_finished_run_ids: set[str] = set()


def _fb_profile_url(username: str) -> str:
    from platforms.facebook.profile_url import normalize_facebook_profile_input

    nav, _, _ = normalize_facebook_profile_input(username)
    return nav


def _stage_list(job: ApifyRefreshJob) -> list[dict]:
    stages = job.apify_stages
    if isinstance(stages, list):
        return [dict(x) for x in stages]
    return []


def _save_stages(job: ApifyRefreshJob, stages: list[dict], **extra_fields) -> ApifyRefreshJob:
    fields = ["apify_stages", "updated_at", *extra_fields.keys()]
    for k, v in extra_fields.items():
        setattr(job, k, v)
    job.apify_stages = stages
    job.save(update_fields=fields)
    return job


def _build_input(job: ApifyRefreshJob, stage: str) -> dict[str, Any]:
    account = job.account
    plat = job.platform
    uname = (account.username or "").strip()

    if plat == Platform.TIKTOK:
        return {"profiles": [uname.lstrip("@")]}

    if plat == Platform.FACEBOOK:
        if stage == "playcount":
            extra = job.run_detail_extra or {}
            urls = extra.get("reel_urls") or []
            return {
                "urlsText": "\n".join(urls),
                "maxConcurrency": 8,
                "maxRetriesPerUrl": 3,
            }
        max_posts = int(getattr(settings, "FACEBOOK_MAX_POSTS", 80) or 80)
        return {
            "startUrls": [{"url": _fb_profile_url(uname)}],
            "maxPosts": max_posts,
            "includeProfileInfo": True,
        }

    if plat == Platform.INSTAGRAM:
        handle = uname.lstrip("@")
        if stage == "posts":
            return {
                "directUrls": [f"https://www.instagram.com/{handle}/"],
                "resultsType": "posts",
                "resultsLimit": 80,
            }
        return {"usernames": [handle]}
    if plat == Platform.YOUTUBE:
        return {
            "startUrls": [f"https://www.youtube.com/@{uname.lstrip('@')}"],
            "maxResult": 30,
            "maxResults": 30,
        }
    if plat == Platform.REDDIT:
        sub = re.sub(r"^https?://(?:www\.)?reddit\.com/", "", uname.strip(), flags=re.I)
        sub = sub.split("?", 1)[0].split("#", 1)[0].strip("/")
        if sub.lower().startswith("r/"):
            sub = sub[2:]
        sub = sub.split("/", 1)[0].strip()
        return {
            "urls": [f"https://www.reddit.com/r/{sub}/"],
            "maxPostsPerSource": 30,
            "sort": "hot",
            "includeComments": False,
        }
    if plat == Platform.RUMBLE:
        rumble_input = uname.strip()
        if not re.match(r"^https?://", rumble_input, flags=re.I):
            rumble_input = f"https://rumble.com/c/{rumble_input.lstrip('@')}"
        return {
            "queries": [rumble_input],
            "contentTypes": ["videos"],
            "maxItems": 200,
        }

    raise ValueError(f"Неподдерживаемая платформа Apify: {plat}")


def _next_stage(job: ApifyRefreshJob, completed_stage: str) -> str | None:
    plat = job.platform
    if plat == Platform.TIKTOK:
        return None
    if plat == Platform.FACEBOOK:
        if completed_stage == "profile":
            return "playcount"
        return None
    if plat == Platform.INSTAGRAM:
        if completed_stage == "profile":
            return "posts"
        return None
    if plat in (Platform.YOUTUBE, Platform.REDDIT, Platform.RUMBLE):
        return None
    return None


def _first_stage(platform: str) -> str:
    if platform in (Platform.TIKTOK, Platform.YOUTUBE, Platform.REDDIT, Platform.RUMBLE):
        return "scrape"
    return "profile"


def _start_stage(job_id: int, stage: str) -> None:
    job = ApifyRefreshJob.objects.select_related("account").get(pk=job_id)
    if job.status in (ApifyRefreshJobStatus.SUCCEEDED, ApifyRefreshJobStatus.FAILED, ApifyRefreshJobStatus.ABORTED):
        return
    if not acquire_run_slot(timeout=7200.0):
        ApifyRefreshJob.objects.filter(pk=job_id).update(status=ApifyRefreshJobStatus.QUEUED)
        return

    actor = actor_for_stage(job.platform, stage)
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
    except Exception as exc:
        release_run_slot()
        logger.exception("apify.start_stage_failed", extra={"job_id": job_id, "stage": stage})
        _fail_job(job, str(exc))


def start_job_pipeline(job_id: int) -> None:
    """Запустить первую стадию (из dispatch или после освобождения слота)."""
    job = ApifyRefreshJob.objects.select_related("account").get(pk=job_id)
    if job.status != ApifyRefreshJobStatus.QUEUED:
        return
    ApifyRefreshJob.objects.filter(pk=job_id).update(status=ApifyRefreshJobStatus.STARTING)
    stage = _first_stage(job.platform)
    threading.Thread(
        target=_start_stage,
        args=(job_id, stage),
        daemon=True,
        name=f"apify-start-{job_id}-{stage}",
    ).start()


def _prepare_facebook_playcount(job: ApifyRefreshJob, crowd_items: list[dict]) -> bool:
    reel_urls: list[str] = []
    for p in crowd_items:
        if not p.get("postId"):
            continue
        u = str(p.get("postUrl") or "")
        if "/reel/" in u:
            reel_urls.append(u)
    extra = dict(job.run_detail_extra or {})
    extra["crowd_items"] = crowd_items
    extra["reel_urls"] = reel_urls
    job.run_detail_extra = extra
    job.save(update_fields=["run_detail_extra", "updated_at"])
    return bool(reel_urls)


def _normalize_and_apply(job: ApifyRefreshJob) -> None:
    account = job.account
    extra = dict(job.run_detail_extra or {})
    stages = _stage_list(job)
    plat = job.platform

    if plat == Platform.TIKTOK:
        ds = stages[-1].get("dataset_id") if stages else job.apify_dataset_id
        items = client.fetch_dataset_items(str(ds))
        payload = normalize_tiktok(items, run_succeeded=True)
    elif plat == Platform.FACEBOOK:
        crowd = extra.get("crowd_items") or []
        play_ds = None
        play_ok = False
        for st in stages:
            if st.get("stage") == "playcount" and st.get("status") == "SUCCEEDED":
                play_ds = st.get("dataset_id")
                play_ok = True
        play_items = client.fetch_dataset_items(str(play_ds)) if play_ds else []
        existing_views = {
            p.external_id: int(p.view_count or 0)
            for p in Post.objects.filter(account=account).only("external_id", "view_count")
        }
        prof_ok = any(
            st.get("stage") == "profile" and st.get("status") == "SUCCEEDED" for st in stages
        )
        payload = normalize_facebook(
            crowd,
            play_items,
            profile_succeeded=prof_ok,
            playcount_succeeded=play_ok,
            existing_views=existing_views,
        )
    elif plat == Platform.INSTAGRAM:
        prof_items: list[dict] = []
        post_items: list[dict] = []
        prof_ok = posts_ok = False
        for st in stages:
            if st.get("status") != "SUCCEEDED":
                continue
            ds = st.get("dataset_id")
            if not ds:
                continue
            data = client.fetch_dataset_items(str(ds))
            if st.get("stage") == "profile":
                prof_items = data
                prof_ok = True
            elif st.get("stage") == "posts":
                post_items = data
                posts_ok = True
        existing_likes = {
            p.external_id: int(p.like_count or 0)
            for p in Post.objects.filter(account=account).only("external_id", "like_count")
        }
        payload = normalize_instagram(
            prof_items,
            post_items,
            profile_succeeded=prof_ok,
            posts_succeeded=posts_ok,
            existing_likes=existing_likes,
        )
    elif plat == Platform.YOUTUBE:
        ds = stages[-1].get("dataset_id") if stages else job.apify_dataset_id
        items = client.fetch_dataset_items(str(ds))
        payload = normalize_youtube(items, username=account.username or "")
    elif plat == Platform.REDDIT:
        ds = stages[-1].get("dataset_id") if stages else job.apify_dataset_id
        items = client.fetch_dataset_items(str(ds))
        payload = normalize_reddit(items, username=account.username or "")
    elif plat == Platform.RUMBLE:
        ds = stages[-1].get("dataset_id") if stages else job.apify_dataset_id
        items = client.fetch_dataset_items(str(ds))
        payload = normalize_rumble(items, username=account.username or "")
    else:
        raise ValueError(f"Платформа {plat} не поддерживается")

    apply_normalized_refresh(account.pk, payload)
    job.status = ApifyRefreshJobStatus.SUCCEEDED
    job.finished_at = timezone.now()
    job.error_message = ""
    job.normalized_preview = {
        "post_count": len(payload.get("_posts") or []),
        "partial": bool(payload.get("_partial")),
    }
    job.save(
        update_fields=[
            "status",
            "finished_at",
            "error_message",
            "normalized_preview",
            "updated_at",
        ],
    )
    usage = {}
    for st in stages:
        usage = {**usage, **(st.get("usage") or {})}
    on_apify_job_finished(job, success=True, detail="")


def _fail_job(job: ApifyRefreshJob, message: str) -> None:
    from accounts.views import _mark_profile_unavailable_if_applicable

    job.status = ApifyRefreshJobStatus.FAILED
    job.finished_at = timezone.now()
    job.error_message = message[:4000]
    job.save(update_fields=["status", "finished_at", "error_message", "updated_at"])
    try:
        _mark_profile_unavailable_if_applicable(job.account, ValueError(message))
    except Exception:
        pass
    on_apify_job_finished(job, success=False, detail=message)


def handle_run_terminal(job_id: int, run_id: str, run_meta: dict[str, Any]) -> None:
    global _finished_run_ids
    with _finish_lock:
        if run_id in _finished_run_ids:
            return
        _finished_run_ids.add(run_id)
        if len(_finished_run_ids) > 5000:
            _finished_run_ids.clear()

    try:
        job = ApifyRefreshJob.objects.select_related("account").get(pk=job_id)
    except ApifyRefreshJob.DoesNotExist:
        release_run_slot()
        return

    if job.status in (ApifyRefreshJobStatus.SUCCEEDED, ApifyRefreshJobStatus.FAILED, ApifyRefreshJobStatus.ABORTED):
        release_run_slot()
        return

    terminal = str(run_meta.get("status") or "")
    stages = _stage_list(job)
    stage_name = ""
    stage_idx = -1
    for i, st in enumerate(stages):
        if str(st.get("run_id")) == run_id:
            stage_name = str(st.get("stage") or "")
            stage_idx = i
            st["status"] = terminal
            st["usage"] = client.run_usage(run_meta)
            if not st.get("dataset_id"):
                st["dataset_id"] = run_meta.get("defaultDatasetId")
            break

    usage_extra = dict(job.run_detail_extra or {})
    usage_extra["last_usage"] = client.run_usage(run_meta)
    job.run_detail_extra = usage_extra

    if terminal != "SUCCEEDED":
        release_run_slot()
        if stage_name == "profile" and job.platform in (Platform.FACEBOOK, Platform.INSTAGRAM):
            _fail_job(job, f"Apify {stage_name}: {terminal}")
        elif stage_name == "playcount" and job.platform == Platform.FACEBOOK:
            job = _save_stages(job, stages)
            try:
                _normalize_and_apply(job)
            except Exception as exc:
                _fail_job(job, str(exc))
        elif stage_name == "posts" and job.platform == Platform.INSTAGRAM:
            _fail_job(job, f"Apify posts: {terminal}")
        else:
            _fail_job(job, f"Apify run {terminal}")
        return

    if stage_idx >= 0 and stage_name == "profile" and job.platform == Platform.FACEBOOK:
        ds = stages[stage_idx].get("dataset_id") or job.apify_dataset_id
        crowd_items = client.fetch_dataset_items(str(ds))
        job = _save_stages(job, stages)
        if not _prepare_facebook_playcount(job, crowd_items):
            release_run_slot()
            try:
                _normalize_and_apply(job)
            except Exception as exc:
                _fail_job(job, str(exc))
            return
        nxt = _next_stage(job, stage_name)
        release_run_slot()
        if nxt:
            threading.Thread(
                target=_start_stage,
                args=(job.pk, nxt),
                daemon=True,
                name=f"apify-next-{job.pk}-{nxt}",
            ).start()
        return

    job = _save_stages(job, stages)
    nxt = _next_stage(job, stage_name)
    release_run_slot()
    if nxt:
        threading.Thread(
            target=_start_stage,
            args=(job.pk, nxt),
            daemon=True,
            name=f"apify-next-{job.pk}-{nxt}",
        ).start()
        return

    try:
        _normalize_and_apply(job)
    except Exception as exc:
        logger.exception("apify.apply_failed", extra={"job_id": job.pk})
        _fail_job(job, str(exc))


def process_queued_jobs() -> None:
    """Попытаться стартовать queued jobs при наличии слота."""
    from .pool import active_run_count, max_concurrent_runs

    if active_run_count() >= max_concurrent_runs():
        return
    pending = (
        ApifyRefreshJob.objects.filter(status=ApifyRefreshJobStatus.QUEUED)
        .order_by("created_at")[: max_concurrent_runs()]
    )
    for job in pending:
        start_job_pipeline(job.pk)


def poll_running_jobs() -> None:
    """Fallback polling для run без webhook."""
    jobs = ApifyRefreshJob.objects.filter(
        status__in=[ApifyRefreshJobStatus.STARTING, ApifyRefreshJobStatus.RUNNING],
    ).select_related("account")
    for job in jobs:
        run_id = (job.apify_run_id or "").strip()
        if not run_id:
            continue
        try:
            meta = client.get_run(run_id)
        except Exception as exc:
            logger.warning("apify.poll_failed", extra={"job_id": job.pk, "error": str(exc)})
            continue
        status = str(meta.get("status") or "")
        if status not in client.TERMINAL_STATUSES:
            continue
        started = job.started_at
        if started:
            elapsed = (timezone.now() - started).total_seconds()
            if elapsed > poll_max_wait_sec(job.platform) and status == "RUNNING":
                try:
                    client.abort_run(run_id)
                except Exception:
                    pass
                _fail_job(job, "Превышено время ожидания Apify")
                release_run_slot()
                continue
        threading.Thread(
            target=handle_run_terminal,
            args=(job.pk, run_id, meta),
            daemon=True,
            name=f"apify-finish-{job.pk}",
        ).start()
