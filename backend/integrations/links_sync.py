"""Синхронизация link_click_count при обновлении аккаунта."""

from __future__ import annotations

import logging
import threading
from typing import TYPE_CHECKING

from integrations.account_profile_url import account_profile_url
from integrations.links_client import LinksApiError, links_api_configured, resolve_clicks_for_profile_urls
from integrations.links_match import normalize_account_label, platform_username_key

from accounts.models import Account, AccountSnapshot

log = logging.getLogger(__name__)

_tls = threading.local()


def _clicks_from_resolved(resolved: dict[str, int], profile_url: str) -> int:
    pu = (profile_url or "").strip()
    if not pu:
        return 0
    if pu in resolved:
        return int(resolved[pu])
    nk = normalize_account_label(pu)
    if nk:
        for key, value in resolved.items():
            if normalize_account_label(key) == nk:
                return int(value)
        for variant in (pu.rstrip("/"), pu.rstrip("/") + "/"):
            if variant in resolved:
                return int(resolved[variant])
    return 0


def _lookup_clicks(index: dict[str, int], account: Account) -> int:
    profile_url = account_profile_url(account)
    keys: list[str] = []
    if profile_url:
        nk = normalize_account_label(profile_url)
        if nk:
            keys.append(nk)
    pk = platform_username_key(account.platform, account.username)
    if pk:
        keys.append(pk)
    for key in keys:
        if key in index:
            return int(index[key])
    return 0


def build_links_clicks_index(accounts: list[Account]) -> dict[str, int]:
    """Индекс normalize-key → total_clicks через POST resolve-clicks (батчами)."""
    if not links_api_configured() or not accounts:
        return {}
    urls: list[str] = []
    for acc in accounts:
        pu = account_profile_url(acc)
        if pu:
            urls.append(pu)
    if not urls:
        return {}
    try:
        resolved = resolve_clicks_for_profile_urls(urls)
    except LinksApiError as exc:
        log.warning("links_sync.build_index_failed: %s", exc)
        return {}
    index: dict[str, int] = {}
    for acc in accounts:
        pu = account_profile_url(acc)
        if not pu:
            continue
        clicks = _clicks_from_resolved(resolved, pu)
        nk = normalize_account_label(pu)
        if nk:
            index[nk] = clicks
        pk = platform_username_key(acc.platform, acc.username)
        if pk:
            index[pk] = clicks
    return index


def begin_refresh_all_links(accounts: list[Account]) -> None:
    _tls.clicks_index = build_links_clicks_index(accounts)


def clear_refresh_all_links() -> None:
    if hasattr(_tls, "clicks_index"):
        del _tls.clicks_index


def refresh_link_clicks_batch(accounts: list[Account]) -> dict:
    """
    Обновить link_click_count и сегодняшний снимок без scrape платформы.
    Возвращает {updated, changed, skipped, total, items, errors}.
    """
    from django.db import transaction

    if not links_api_configured():
        raise LinksApiError("Links API не настроен (LINKS_API_URL / LINKS_API_TOKEN)")
    if not accounts:
        return {
            "updated": 0,
            "changed": 0,
            "skipped": 0,
            "total": 0,
            "items": [],
            "errors": [],
        }

    index = build_links_clicks_index(accounts)
    with_urls = sum(1 for a in accounts if account_profile_url(a))
    if with_urls and not index:
        raise LinksApiError(
            "Links API не вернул клики по URL профилей. "
            "Проверьте LINKS_API_URL, LINKS_API_TOKEN и что в Links label совпадает с URL профиля."
        )

    updated = 0
    changed = 0
    skipped = 0
    errors: list[dict] = []
    items: list[dict] = []

    for account in accounts:
        try:
            if not account_profile_url(account):
                skipped += 1
                continue
            if not index:
                skipped += 1
                continue

            clicks = _lookup_clicks(index, account)
            old_clicks = int(account.link_click_count or 0)
            snap, _ = account.take_snapshot_if_needed()
            with transaction.atomic():
                Account.objects.filter(pk=account.pk).update(link_click_count=clicks)
                AccountSnapshot.objects.filter(pk=snap.pk).update(link_click_count=clicks)
            account.link_click_count = clicks
            updated += 1
            if clicks != old_clicks:
                changed += 1
            items.append({"id": account.id, "link_click_count": clicks})
        except Exception as exc:
            log.warning(
                "links_sync.batch_item_failed account_id=%s: %s",
                account.id,
                exc,
            )
            errors.append({"id": account.id, "detail": str(exc)})

    return {
        "updated": updated,
        "changed": changed,
        "skipped": skipped,
        "total": len(accounts),
        "items": items,
        "errors": errors,
    }


def sync_link_clicks_for_account(account: Account) -> int:
    """Вернуть актуальное число переходов; при ошибке API — прежнее значение в БД."""
    if not links_api_configured():
        return int(account.link_click_count or 0)

    index = getattr(_tls, "clicks_index", None)
    if index is None:
        index = build_links_clicks_index([account])

    if not index and account_profile_url(account):
        return int(account.link_click_count or 0)

    try:
        return _lookup_clicks(index, account)
    except Exception as exc:
        log.warning(
            "links_sync.lookup_failed account_id=%s: %s",
            account.id,
            exc,
        )
        return int(account.link_click_count or 0)
