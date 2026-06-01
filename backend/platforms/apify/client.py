"""REST-клиент Apify API v2 (httpx)."""
from __future__ import annotations

import logging
import time
from typing import Any
from urllib.parse import quote

import httpx
from django.conf import settings

from .config import apify_token

logger = logging.getLogger(__name__)

API_BASE = "https://api.apify.com/v2"
TERMINAL_STATUSES = frozenset({"SUCCEEDED", "FAILED", "ABORTED", "TIMED-OUT"})


def actor_api_id(actor_id: str) -> str:
    """crowdpull/facebook-profile-scraper → crowdpull~facebook-profile-scraper"""
    return str(actor_id or "").strip().replace("/", "~")


def _headers() -> dict[str, str]:
    token = apify_token()
    if not token:
        raise RuntimeError("APIFY_TOKEN не задан")
    return {"Authorization": f"Bearer {token}"}


def _client() -> httpx.Client:
    return httpx.Client(timeout=180.0, headers=_headers())


def build_webhook_url() -> str | None:
    base = (getattr(settings, "APIFY_WEBHOOK_BASE_URL", "") or "").strip().rstrip("/")
    secret = (getattr(settings, "APIFY_WEBHOOK_SECRET", "") or "").strip()
    if not base or not secret:
        return None
    return f"{base}/api/internal/apify/webhook/?token={quote(secret, safe='')}"


def start_run(actor_id: str, run_input: dict, *, wait_secs: int = 0) -> dict[str, Any]:
    act = actor_api_id(actor_id)
    params: dict[str, str | int] = {}
    if wait_secs > 0:
        params["waitForFinish"] = wait_secs
    # Webhook настраивается отдельно в Console или через poller (actor input не смешиваем).
    with _client() as c:
        r = c.post(f"{API_BASE}/acts/{act}/runs", json=run_input, params=params or None)
        r.raise_for_status()
        return r.json()["data"]


def get_run(run_id: str) -> dict[str, Any]:
    with _client() as c:
        r = c.get(f"{API_BASE}/actor-runs/{run_id}")
        r.raise_for_status()
        return r.json()["data"]


def abort_run(run_id: str) -> None:
    with _client() as c:
        r = c.post(f"{API_BASE}/actor-runs/{run_id}/abort")
        if r.status_code not in (200, 404):
            r.raise_for_status()


def fetch_dataset_items(dataset_id: str, *, limit: int = 1000) -> list[dict]:
    with _client() as c:
        r = c.get(
            f"{API_BASE}/datasets/{dataset_id}/items",
            params={"limit": limit, "clean": "true"},
        )
        r.raise_for_status()
        data = r.json()
        if isinstance(data, list):
            return data
        return []


def wait_for_run(
    run_id: str,
    *,
    poll_sec: int | None = None,
    max_wait_sec: int | None = None,
) -> dict[str, Any]:
    poll = poll_sec or int(getattr(settings, "APIFY_POLL_INTERVAL_SEC", 15) or 15)
    max_wait = max_wait_sec or 600
    deadline = time.monotonic() + max_wait
    last: dict[str, Any] = {}
    while time.monotonic() < deadline:
        last = get_run(run_id)
        status = str(last.get("status") or "")
        if status in TERMINAL_STATUSES:
            return last
        time.sleep(poll)
    raise TimeoutError(f"Apify run {run_id} не завершился за {max_wait} с")


def run_usage(meta: dict) -> dict[str, Any]:
    stats = meta.get("stats") or {}
    billing = meta.get("usageTotalUsd") or meta.get("usageUsd")
    cu = stats.get("computeUnits") or meta.get("computeUnits")
    out: dict[str, Any] = {}
    if cu is not None:
        out["computeUnits"] = cu
    if billing is not None:
        out["usageTotalUsd"] = billing
    started = meta.get("startedAt")
    finished = meta.get("finishedAt")
    if started and finished:
        try:
            from django.utils.dateparse import parse_datetime

            a = parse_datetime(str(started))
            b = parse_datetime(str(finished))
            if a and b:
                out["durationMs"] = int((b - a).total_seconds() * 1000)
        except Exception:
            pass
    return out
