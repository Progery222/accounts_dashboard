"""Webhook Apify → завершение run."""
from __future__ import annotations

import json
import logging
import threading

from django.conf import settings
from django.http import HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from accounts.models import ApifyRefreshJob

logger = logging.getLogger(__name__)


def _find_job_by_run_id(run_id: str) -> ApifyRefreshJob | None:
    run_id = str(run_id or "").strip()
    if not run_id:
        return None
    job = ApifyRefreshJob.objects.filter(apify_run_id=run_id).order_by("-id").first()
    if job:
        return job
    for j in ApifyRefreshJob.objects.filter(
        status__in=["queued", "starting", "running"],
    ).order_by("-id")[:200]:
        for st in j.apify_stages or []:
            if str(st.get("run_id")) == run_id:
                return j
    return None


@csrf_exempt
@require_POST
def apify_webhook(request):
    secret = (getattr(settings, "APIFY_WEBHOOK_SECRET", "") or "").strip()
    if secret and request.GET.get("token") != secret:
        return HttpResponse("forbidden", status=403)

    try:
        body = json.loads(request.body.decode("utf-8") or "{}")
    except json.JSONDecodeError:
        return HttpResponse("bad json", status=400)

    run_id = str(body.get("runId") or body.get("resourceId") or "").strip()
    if not run_id:
        return HttpResponse("ok")

    job = _find_job_by_run_id(run_id)
    if not job:
        logger.warning("apify.webhook_unknown_run", extra={"run_id": run_id})
        return HttpResponse("ok")

    from platforms.apify import client
    from platforms.apify.pipeline import handle_run_terminal

    try:
        meta = client.get_run(run_id)
    except Exception as exc:
        logger.warning("apify.webhook_get_run_failed", extra={"run_id": run_id, "error": str(exc)})
        return HttpResponse("ok")

    threading.Thread(
        target=handle_run_terminal,
        args=(job.pk, run_id, meta),
        daemon=True,
        name=f"apify-wh-{job.pk}",
    ).start()
    return HttpResponse("ok")
