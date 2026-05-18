"""HTTP-клиент Links API (клики по коротким ссылкам в bio)."""

from __future__ import annotations

import logging
from typing import Any

import httpx
from django.conf import settings

from integrations.links_match import normalize_account_label

log = logging.getLogger(__name__)

RESOLVE_CLICKS_PATH = "/api/v1/links/resolve-clicks"
RESOLVE_BATCH_SIZE = 500


class LinksApiError(Exception):
    pass


def _base_url() -> str | None:
    raw = (getattr(settings, "LINKS_API_URL", None) or "").strip().rstrip("/")
    return raw or None


def _token() -> str | None:
    raw = (getattr(settings, "LINKS_API_TOKEN", None) or "").strip()
    return raw or None


def links_api_configured() -> bool:
    return bool(_base_url() and _token())


def _headers() -> dict[str, str]:
    token = _token()
    if not token:
        raise LinksApiError("LINKS_API_TOKEN не задан")
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


def _request(method: str, path: str, *, json: dict | None = None, timeout: float | None = None) -> Any:
    base = _base_url()
    if not base:
        raise LinksApiError("LINKS_API_URL не задан")
    timeout = timeout if timeout is not None else float(getattr(settings, "LINKS_API_TIMEOUT", 25) or 25)
    url = f"{base}{path}"
    try:
        resp = httpx.request(method, url, headers=_headers(), json=json, timeout=timeout)
    except httpx.RequestError as exc:
        raise LinksApiError(str(exc)) from exc
    if resp.status_code == 503:
        raise LinksApiError("Links API: токен не настроен на сервере (503)")
    if resp.status_code == 401:
        raise LinksApiError("Links API: неверный токен (401)")
    if resp.status_code >= 400:
        detail = resp.text[:300]
        raise LinksApiError(f"Links API HTTP {resp.status_code}: {detail}")
    if resp.status_code == 204:
        return None
    return resp.json()


def _bulk_resolve_unavailable(exc: LinksApiError) -> bool:
    """404/405 — старый деплой или эндпоинт ещё не поднялся после релиза."""
    msg = str(exc)
    return "404" in msg or "405" in msg


def fetch_all_links_index() -> dict[str, int]:
    """Fallback: normalize(label) → сумма total_clicks (полная пагинация GET /links)."""
    index: dict[str, int] = {}
    offset = 0
    page_size = 500
    while True:
        data = _request("GET", f"/api/v1/links?limit={page_size}&offset={offset}")
        items = data.get("items") or []
        for item in items:
            key = normalize_account_label(item.get("label"))
            if not key:
                continue
            clicks = int(item.get("total_clicks") or 0)
            index[key] = index.get(key, 0) + clicks
        total = int(data.get("total") or 0)
        offset += len(items)
        if not items or offset >= total:
            break
    return index


def _resolve_from_paginated_list(profile_urls: list[str]) -> dict[str, int]:
    index = fetch_all_links_index()
    return {
        pu: int(index.get(normalize_account_label(pu) or "", 0))
        for pu in profile_urls
    }


def _row_profile_keys(row: dict) -> list[str]:
    keys: list[str] = []
    for field in ("profile_url", "label", "url"):
        raw = str(row.get(field) or "").strip()
        if raw:
            keys.append(raw)
    return keys


def _parse_resolve_response(data: dict, *, expected_urls: list[str]) -> dict[str, int]:
    """Сопоставление по URL/label, не по порядку строк (API может вернуть items в другом порядке)."""
    items = data.get("items") or []
    if len(items) != len(expected_urls):
        log.warning(
            "links.resolve_clicks: items count %s != requested %s",
            len(items),
            len(expected_urls),
        )

    by_norm: dict[str, int] = {}
    for row in items:
        clicks = int(row.get("total_clicks") or 0)
        for raw in _row_profile_keys(row):
            nk = normalize_account_label(raw)
            if nk:
                by_norm[nk] = clicks
            by_norm[raw.strip().rstrip("/")] = clicks
            by_norm[raw.strip().rstrip("/") + "/"] = clicks

    out: dict[str, int] = {}
    for pu in expected_urls:
        pu = str(pu).strip()
        nk = normalize_account_label(pu)
        clicks = None
        if nk and nk in by_norm:
            clicks = by_norm[nk]
        else:
            for variant in (pu, pu.rstrip("/"), pu.rstrip("/") + "/"):
                if variant in by_norm:
                    clicks = by_norm[variant]
                    break
        out[pu] = int(clicks if clicks is not None else 0)
    return out


def resolve_clicks_for_profile_urls(profile_urls: list[str]) -> dict[str, int]:
    """
    POST /api/v1/links/resolve-clicks (батчами до 500 URL).
    При 404/405 — fallback на GET /api/v1/links с пагинацией.
    """
    urls = [str(u).strip() for u in profile_urls if u and str(u).strip()]
    if not urls:
        return {}

    out: dict[str, int] = {}
    for start in range(0, len(urls), RESOLVE_BATCH_SIZE):
        chunk = urls[start : start + RESOLVE_BATCH_SIZE]
        try:
            data = _request(
                "POST",
                RESOLVE_CLICKS_PATH,
                json={"profile_urls": chunk},
            )
        except LinksApiError as exc:
            if not _bulk_resolve_unavailable(exc):
                raise
            log.warning(
                "links.resolve_clicks: bulk unavailable (%s), falling back to GET /links pagination",
                exc,
            )
            return _resolve_from_paginated_list(urls)
        out.update(_parse_resolve_response(data, expected_urls=chunk))
    return out


def check_links_api() -> bool:
    if not links_api_configured():
        return False
    try:
        _request("GET", "/api/v1/me", timeout=10)
        return True
    except LinksApiError:
        return False
