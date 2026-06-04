"""Фильтры охвата автообновления: платформы и профили."""

from __future__ import annotations

from django.db.models import Q

from accounts.models import Platform


def normalize_auto_refresh_platforms(raw) -> list[str]:
    if not isinstance(raw, list):
        return []
    allowed = {v for v, _ in Platform.choices}
    out: list[str] = []
    for item in raw:
        v = str(item).strip().lower()
        if v in allowed and v not in out:
            out.append(v)
    return out


def normalize_auto_refresh_profile_ids(raw) -> list:
    """Список int id профилей и/или строки ``none`` (аккаунты без профиля)."""
    if not isinstance(raw, list):
        return []
    out: list = []
    for item in raw:
        if str(item).strip().lower() == "none":
            if "none" not in out:
                out.append("none")
            continue
        try:
            n = int(item)
        except (TypeError, ValueError):
            continue
        if n not in out:
            out.append(n)
    return out


def normalize_auto_refresh_owner_ids(raw) -> list:
    """Список int id владельцев и/или строки ``none`` (аккаунты без владельца)."""
    if not isinstance(raw, list):
        return []
    out: list = []
    for item in raw:
        if str(item).strip().lower() == "none":
            if "none" not in out:
                out.append("none")
            continue
        try:
            n = int(item)
        except (TypeError, ValueError):
            continue
        if n not in out:
            out.append(n)
    return out


def apply_auto_refresh_scope(qs, cfg):
    """
    Пустой список платформ/профилей в конфиге = без ограничения (все).
    Непустой список = только перечисленные.
    """
    platforms = normalize_auto_refresh_platforms(
        getattr(cfg, "auto_refresh_platforms", None) or [],
    )
    if platforms:
        qs = qs.filter(platform__in=platforms)

    profile_ids = normalize_auto_refresh_profile_ids(
        getattr(cfg, "auto_refresh_profile_ids", None) or [],
    )
    if profile_ids:
        clause = Q()
        int_ids = [x for x in profile_ids if isinstance(x, int)]
        if int_ids:
            clause |= Q(profile_id__in=int_ids)
        if "none" in profile_ids:
            clause |= Q(profile__isnull=True)
        if clause:
            qs = qs.filter(clause)

    owner_ids = normalize_auto_refresh_owner_ids(
        getattr(cfg, "auto_refresh_owner_ids", None) or [],
    )
    if owner_ids:
        clause = Q()
        int_ids = [x for x in owner_ids if isinstance(x, int)]
        if int_ids:
            clause |= Q(owner_id__in=int_ids)
        if "none" in owner_ids:
            clause |= Q(owner__isnull=True)
        if clause:
            qs = qs.filter(clause)
    return qs
