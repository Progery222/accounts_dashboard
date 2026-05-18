"""HTTP-клиент к API дашборда (синхронизация профилей, аккаунтов, аудитории)."""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from django.conf import settings
from django.utils import dateparse
from django.utils import timezone as dj_tz

from .models import Account, AccountAudienceMembership, AudienceMember, Profile, SUBS_SUBSCRIBER_PLATFORM_VALUES


def _dashboard_base() -> str:
    return getattr(settings, "DASHBOARD_API_URL", "http://127.0.0.1:8000").rstrip("/")


def _http_json(
    method: str,
    path: str,
    *,
    body: dict | None = None,
    timeout: int = 120,
    extra_headers: dict[str, str] | None = None,
) -> Any:
    url = f"{_dashboard_base()}{path}"
    data = None if body is None else json.dumps(body).encode("utf-8")
    headers = {
        "Accept": "application/json",
        **({"Content-Type": "application/json"} if data is not None else {}),
    }
    if extra_headers:
        headers.update(extra_headers)
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers=headers,
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw.strip() else None
    except urllib.error.HTTPError as e:
        try:
            err_body = e.read().decode("utf-8")
            payload = json.loads(err_body) if err_body.strip() else {}
        except Exception:
            payload = {}
        detail = payload.get("detail") if isinstance(payload, dict) else None
        raise RuntimeError(detail or f"HTTP {e.code} {path}") from e


def sync_profiles_and_accounts() -> dict[str, int]:
    """Тянет профили и аккаунты выбранных площадок с дашборда в локальную БД subs."""
    profiles_raw = _http_json("GET", "/api/accounts/profiles/?include_hidden_profiles=1")
    if not isinstance(profiles_raw, list):
        profiles_raw = []
    p_n = 0
    for p in profiles_raw:
        if not isinstance(p, dict) or p.get("id") is None:
            continue
        pid = int(p["id"])
        Profile.objects.update_or_create(
            mirror_dashboard_id=pid,
            defaults={
                "name": str(p.get("name") or f"Профиль {pid}")[:255],
                "description": str(p.get("description") or "")[:5000],
                "color": str(p.get("color") or "#6366f1")[:7],
                "avatar_url": str(p.get("avatar_url") or "")[:1024],
                "is_hidden": bool(p.get("is_hidden")),
            },
        )
        p_n += 1

    accounts_raw = _http_json("GET", "/api/accounts/?include_hidden=1")
    if not isinstance(accounts_raw, list):
        accounts_raw = []
    a_n = 0
    for row in accounts_raw:
        if not isinstance(row, dict):
            continue
        plat = str(row.get("platform") or "").lower()
        if plat not in SUBS_SUBSCRIBER_PLATFORM_VALUES:
            continue
        aid = int(row["id"])
        username = str(row.get("username") or "").strip()
        if not username:
            continue
        prof = None
        raw_pid = row.get("profile_id")
        if raw_pid is not None:
            try:
                prof = Profile.objects.filter(mirror_dashboard_id=int(raw_pid)).first()
            except (TypeError, ValueError):
                prof = None
        defaults: dict = {
            "username": username[:255],
            "platform": plat,
            "profile": prof,
            "display_name": str(row.get("display_name") or "")[:255],
            "avatar_url": str(row.get("avatar_url") or "")[:1024],
            "bio": str(row.get("bio") or "")[:5000],
            "follower_count": int(row.get("follower_count") or 0),
            "like_count": int(row.get("like_count") or 0),
            "view_count": int(row.get("view_count") or 0),
            "post_count": int(row.get("post_count") or 0),
            "profile_unavailable": bool(row.get("profile_unavailable")),
        }
        raw_synced = row.get("audience_last_synced_at")
        if raw_synced not in (None, ""):
            dt = dateparse.parse_datetime(str(raw_synced))
            if dt is not None:
                if dj_tz.is_naive(dt):
                    dt = dj_tz.make_aware(dt, dj_tz.get_current_timezone())
                defaults["audience_last_synced_at"] = dt

        Account.objects.update_or_create(
            mirror_dashboard_id=aid,
            defaults=defaults,
        )
        a_n += 1

    return {"profiles_upserted": p_n, "accounts_upserted": a_n}


def dashboard_refresh_account(dashboard_account_id: int, body: dict | None = None) -> Any:
    return _http_json(
        "POST",
        f"/api/accounts/{int(dashboard_account_id)}/audience/refresh/",
        body=body if body is not None else {},
        timeout=3600,
    )


def dashboard_stop_audience_scrape() -> None:
    """Прервать Playwright-съём на дашборде (текущий audience/refresh из subs)."""
    _http_json("POST", "/api/accounts/audience-scrape-stop/", body={}, timeout=30)


def import_audience_into_subs(subs_account: Account) -> tuple[int, int]:
    """
    GET /api/accounts/{id}/audience/ на дашборде → строки в subs.

    После успешного обхода всех страниц удаляет связи аккаунт–подписчик, которых
    больше нет в ответе дашборда (отписки от отслеживаемого аккаунта).
    """
    if not subs_account.mirror_dashboard_id:
        raise ValueError("У аккаунта нет mirror_dashboard_id — сначала синхронизация с дашборда.")
    dash_id = int(subs_account.mirror_dashboard_id)
    plat = subs_account.platform
    total_imported = 0
    synced_member_ids: set[int] = set()
    page = 1
    page_size = 100
    full_sync_done = False
    while True:
        payload = _http_json(
            "GET",
            f"/api/accounts/{dash_id}/audience/?page={page}&page_size={page_size}",
            timeout=120,
        )
        if not isinstance(payload, dict):
            break
        results = payload.get("results")
        if not isinstance(results, list):
            break
        count = int(payload.get("count") or 0)
        for row in results:
            if not isinstance(row, dict):
                continue
            uname = str(row.get("username") or "").strip()
            if not uname:
                continue
            existing_member = AudienceMember.objects.filter(
                platform=plat,
                username=uname[:255],
            ).first()
            prev_fn_by_user: dict[str, dict] = {}
            if existing_member and isinstance(existing_member.follower_network, list):
                for x in existing_member.follower_network:
                    if isinstance(x, dict):
                        ku = str(x.get("username") or "").strip().lstrip("@").lower()
                        if ku:
                            prev_fn_by_user[ku] = x
            fn_raw = row.get("follower_network")
            fn_list = fn_raw if isinstance(fn_raw, list) else []
            fn_safe: list = []
            for ent in fn_list:
                if len(fn_safe) >= 100:
                    break
                if not isinstance(ent, dict):
                    continue
                eu = str(ent.get("username") or "").strip().lstrip("@").lower()
                if not eu:
                    continue
                ebio = str(ent.get("bio") or "").strip()[:2000]
                if not ebio:
                    prev = prev_fn_by_user.get(eu)
                    if isinstance(prev, dict):
                        ebio = str(prev.get("bio") or "").strip()[:2000]
                fn_safe.append(
                    {
                        "username": eu[:255],
                        "display_name": str(ent.get("display_name") or "")[:255],
                        "avatar_url": str(ent.get("avatar_url") or "")[:2048],
                        "bio": ebio,
                        "is_private": bool(ent.get("is_private")),
                        "follower_count": int(ent.get("follower_count") or 0),
                        "following_count": int(ent.get("following_count") or 0),
                        "like_count": int(ent.get("like_count") or 0),
                    },
                )
            dash_bio = str(row.get("bio") or "").strip()[:2000]
            defaults: dict = {
                "external_id": str(row.get("external_id") or "")[:160],
                "display_name": str(row.get("display_name") or "")[:255],
                "avatar_url": str(row.get("avatar_url") or "")[:2048],
                "is_private": bool(row.get("is_private")),
                "follower_count": int(row.get("follower_count") or 0),
                "following_count": int(row.get("following_count") or 0),
                "like_count": int(row.get("like_count") or 0),
                "follower_network": fn_safe,
            }
            if dash_bio:
                defaults["bio"] = dash_bio
            elif not existing_member:
                defaults["bio"] = ""
            member, _ = AudienceMember.objects.update_or_create(
                platform=plat,
                username=uname[:255],
                defaults=defaults,
            )
            AccountAudienceMembership.objects.get_or_create(
                account=subs_account,
                member=member,
            )
            synced_member_ids.add(member.pk)
            total_imported += 1
        if page * page_size >= count:
            full_sync_done = True
            break
        if not results:
            break
        page += 1

    pruned = 0
    if full_sync_done:
        stale = AccountAudienceMembership.objects.filter(account=subs_account)
        if synced_member_ids:
            stale = stale.exclude(member_id__in=synced_member_ids)
        pruned, _ = stale.delete()

    subs_account.audience_last_synced_at = dj_tz.now()
    subs_account.save(update_fields=["audience_last_synced_at", "updated_at"])
    return total_imported, pruned


def dashboard_delete_audience_member_by_username(dashboard_account_id: int, username: str) -> None:
    """
    Удалить подписчика из снятой базы на дашборде по нику (ищем через ?search=).
    """
    want = str(username or "").strip().lstrip("@").lower()
    if not want:
        raise ValueError("Пустой username")
    q = urllib.parse.urlencode({"search": want, "page": "1", "page_size": "100"})
    payload = _http_json(
        "GET",
        f"/api/accounts/{int(dashboard_account_id)}/audience/?{q}",
        timeout=90,
    )
    if not isinstance(payload, dict):
        raise RuntimeError("Некорректный ответ списка аудитории дашборда")
    results = payload.get("results")
    if not isinstance(results, list):
        raise RuntimeError("Нет results в ответе аудитории дашборда")
    dash_member_id: int | None = None
    for row in results:
        if not isinstance(row, dict):
            continue
        u = str(row.get("username") or "").strip().lower()
        if u == want and row.get("id") is not None:
            dash_member_id = int(row["id"])
            break
    if dash_member_id is None:
        raise RuntimeError(f"Подписчик @{want} не найден в аудитории дашборда (account {dashboard_account_id})")
    _http_json(
        "DELETE",
        f"/api/accounts/{int(dashboard_account_id)}/audience/{dash_member_id}/",
        timeout=60,
    )
