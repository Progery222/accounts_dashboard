"""
Съём аудитории для клиента subs (заголовок X-Subs-Client: 1).

AccountsStats использует accounts.audience без изменений.
"""
from __future__ import annotations

from pathlib import Path

from .audience import (
    AUDIENCE_SYNC_SUPPORTED_PLATFORMS,
    effective_audience_follower_limit,
    fetch_audience_payload,
    normalize_audience_mode,
    sync_audience_from_payload,
)
from .models import Account, AudienceMember, Platform

_TIKTOK_MAIN_WORKER = (
    Path(__file__).resolve().parent.parent / "platforms" / "tiktok" / "worker.py"
)
_TIKTOK_SUBS_WORKER = (
    Path(__file__).resolve().parent.parent
    / "platforms"
    / "subs"
    / "tiktok_audience_worker.py"
)

SUBS_TIKTOK_ONESHOT_ENV: dict[str, str] = {
    "BROWSER_HEADLESS": "false",
    "TIKTOK_HEADLESS": "false",
    "WORKER_AUTOCLOSE_BROWSER_ON_EXIT": "0",
    "SUBS_ONESHOT_EXIT": "1",
    # Пауза между подписчиками в одном окне (сек): мин,макс
    "SUBS_TIKTOK_ENRICH_GAP_SEC": "4,8",
    "SUBS_TIKTOK_BULK_ACCOUNT_GAP_SEC": "6,12",
}


def _subs_build_audience_payload(
    account: Account,
    *,
    audience_mode: str,
    skip_existing_member_profiles: bool,
    enrich_usernames: list[str] | None,
) -> dict:
    mode = normalize_audience_mode(audience_mode)
    lim = effective_audience_follower_limit()
    payload = {
        "audience_followers": True,
        "username": account.username,
        "limit": lim,
        "max_posts_per_follower": 0,
        "audience_account_id": account.pk,
        "audience_mode": mode,
        "list_only": mode == "list",
        "enrich_only": mode == "enrich",
        "skip_existing_member_profiles": bool(skip_existing_member_profiles),
    }
    if enrich_usernames:
        payload["enrich_usernames"] = list(enrich_usernames)
    return payload


def fetch_audience_payload_subs(
    account: Account,
    *,
    audience_mode: str = "full",
    skip_existing_member_profiles: bool = False,
    enrich_usernames: list[str] | None = None,
) -> dict:
    from .audience_platform_gate import audience_platform_slot
    from .refresh_priority import PRIORITY_BLOCK_MESSAGE, account_refresh_priority_active
    from platforms.worker_pool import call_worker_oneshot, release_worker

    if account_refresh_priority_active():
        raise ValueError(PRIORITY_BLOCK_MESSAGE)

    if account.platform not in AUDIENCE_SYNC_SUPPORTED_PLATFORMS:
        raise ValueError(
            "Съём аудитории поддерживается только для TikTok, Instagram, X и Threads.",
        )

    mode = normalize_audience_mode(audience_mode)
    if mode == "enrich":
        linked = AudienceMember.objects.filter(memberships__account=account).count()
        has_targets = bool(enrich_usernames)
        if linked < 1 and not has_targets:
            raise ValueError(
                "Нет сохранённых подписчиков для обогащения — сначала выполните съём списка (режим list).",
            )

    payload = _subs_build_audience_payload(
        account,
        audience_mode=mode,
        skip_existing_member_profiles=skip_existing_member_profiles,
        enrich_usernames=enrich_usernames,
    )

    if account.platform != Platform.TIKTOK:
        return fetch_audience_payload(
            account,
            audience_mode=mode,
            skip_existing_member_profiles=skip_existing_member_profiles,
            enrich_usernames=enrich_usernames,
        )

    with audience_platform_slot(account.platform):
        if account_refresh_priority_active():
            raise ValueError(PRIORITY_BLOCK_MESSAGE)
        release_worker(_TIKTOK_MAIN_WORKER)
        out = call_worker_oneshot(
            _TIKTOK_SUBS_WORKER,
            payload,
            timeout_sec=3600.0,
            extra_env=dict(SUBS_TIKTOK_ONESHOT_ENV),
        )
    if isinstance(out, dict):
        out.setdefault("audience_mode", mode)
    return out


def refresh_tiktok_bulk_subs(
    accounts: list[Account],
    *,
    audience_mode: str = "enrich",
    skip_existing_member_profiles: bool = False,
    enrich_by_dashboard_id: dict[int, list[str] | None] | None = None,
) -> dict:
    """
    Несколько TikTok-аккаунтов в одном окне Chrome (только subs, X-Subs-Client).
    enrich_by_dashboard_id: dashboard pk → список ников подписчиков (из subs).
    """
    from .audience_platform_gate import audience_platform_slot
    from .refresh_priority import PRIORITY_BLOCK_MESSAGE, account_refresh_priority_active
    from platforms.worker_pool import call_worker_oneshot, release_worker

    if account_refresh_priority_active():
        raise ValueError(PRIORITY_BLOCK_MESSAGE)

    tiktok_accounts = [a for a in accounts if a.platform == Platform.TIKTOK]
    if not tiktok_accounts:
        return {"results": [], "accounts": []}

    mode = normalize_audience_mode(audience_mode)
    jobs: list[dict] = []
    for acc in tiktok_accounts:
        names = None
        if enrich_by_dashboard_id and acc.pk in enrich_by_dashboard_id:
            names = enrich_by_dashboard_id.get(acc.pk)
        jobs.append(
            _subs_build_audience_payload(
                acc,
                audience_mode=mode,
                skip_existing_member_profiles=skip_existing_member_profiles,
                enrich_usernames=names,
            ),
        )

    with audience_platform_slot(Platform.TIKTOK):
        if account_refresh_priority_active():
            raise ValueError(PRIORITY_BLOCK_MESSAGE)
        release_worker(_TIKTOK_MAIN_WORKER)
        worker_out = call_worker_oneshot(
            _TIKTOK_SUBS_WORKER,
            {"subs_tiktok_bulk": True, "jobs": jobs},
            timeout_sec=7200.0,
            extra_env=dict(SUBS_TIKTOK_ONESHOT_ENV),
        )

    if isinstance(worker_out, dict) and worker_out.get("error"):
        raise ValueError(str(worker_out["error"]))

    raw_results = worker_out.get("results") if isinstance(worker_out, dict) else None
    if not isinstance(raw_results, list):
        raise ValueError("Некорректный ответ subs bulk worker")

    by_dash_id = {int(a.pk): a for a in tiktok_accounts}
    synced: list[dict] = []
    for item in raw_results:
        if not isinstance(item, dict):
            continue
        dash_id = int(item.get("audience_account_id") or 0)
        acc = by_dash_id.get(dash_id)
        if acc is None:
            continue
        payload = item.get("payload")
        if not isinstance(payload, dict):
            synced.append(
                {
                    "dashboard_account_id": dash_id,
                    "username": acc.username,
                    "error": "Пустой payload",
                },
            )
            continue
        if payload.get("error"):
            synced.append(
                {
                    "dashboard_account_id": dash_id,
                    "username": acc.username,
                    "error": str(payload["error"]),
                },
            )
            continue
        try:
            out = sync_audience_from_payload(acc, payload, audience_mode=mode)
            synced.append(
                {
                    "dashboard_account_id": dash_id,
                    "username": acc.username,
                    "ok": True,
                    **out,
                },
            )
        except Exception as exc:
            synced.append(
                {
                    "dashboard_account_id": dash_id,
                    "username": acc.username,
                    "error": str(exc),
                },
            )

    return {"subs_tiktok_bulk": True, "results": synced}


def refresh_audience_for_account_subs(
    account: Account,
    *,
    audience_mode: str = "full",
    skip_existing_member_profiles: bool = False,
    enrich_usernames: list[str] | None = None,
) -> dict:
    mode = normalize_audience_mode(audience_mode)
    payload = fetch_audience_payload_subs(
        account,
        audience_mode=mode,
        skip_existing_member_profiles=skip_existing_member_profiles,
        enrich_usernames=enrich_usernames,
    )
    return sync_audience_from_payload(account, payload, audience_mode=mode)
