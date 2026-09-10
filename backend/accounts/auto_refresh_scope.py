"""Фильтры охвата автообновления: платформы, профили, владельцы, группы, страны, домены."""

from __future__ import annotations

from django.db.models import Q

from accounts.models import Platform

# Разрешённые слоты «по времени» (МСК) — совпадают с UI.
SCHEDULE_TIME_SLOTS = ("00:00", "06:00", "12:00", "18:00")


def normalize_schedule_times(raw) -> list[str]:
    if not isinstance(raw, list):
        return []
    allowed = set(SCHEDULE_TIME_SLOTS)
    out: list[str] = []
    for t in raw:
        try:
            h, m = map(int, str(t).split(":"))
            assert 0 <= h <= 23 and 0 <= m <= 59
            hhmm = f"{h:02d}:{m:02d}"
        except Exception:
            continue
        if hhmm in allowed and hhmm not in out:
            out.append(hhmm)
    out.sort()
    return out


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


def _normalize_id_list(raw) -> list:
    """Список int id и/или строки ``none``."""
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


def normalize_auto_refresh_profile_ids(raw) -> list:
    """Список int id профилей и/или строки ``none`` (аккаунты без профиля)."""
    return _normalize_id_list(raw)


def normalize_auto_refresh_group_ids(raw) -> list:
    """Список int id групп и/или строки ``none`` (аккаунты без группы)."""
    return _normalize_id_list(raw)


def normalize_auto_refresh_country_ids(raw) -> list:
    """Список int id стран и/или строки ``none`` (аккаунты без страны)."""
    return _normalize_id_list(raw)


def normalize_auto_refresh_owner_ids(raw) -> list:
    """Список int id владельцев и/или строки ``none`` (аккаунты без владельца)."""
    return _normalize_id_list(raw)


def normalize_auto_refresh_domain_ids(raw) -> list:
    """Список int id доменов и/или строки ``none`` (аккаунты без домена)."""
    return _normalize_id_list(raw)


def _apply_id_scope(qs, ids, field: str):
    if not ids:
        return qs
    clause = Q()
    int_ids = [x for x in ids if isinstance(x, int)]
    if int_ids:
        clause |= Q(**{f"{field}__in": int_ids})
    if "none" in ids:
        clause |= Q(**{f"{field}__isnull": True})
    if clause:
        qs = qs.filter(clause)
    return qs


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

    qs = _apply_id_scope(
        qs,
        normalize_auto_refresh_profile_ids(getattr(cfg, "auto_refresh_profile_ids", None) or []),
        "profile_id",
    )
    qs = _apply_id_scope(
        qs,
        normalize_auto_refresh_owner_ids(getattr(cfg, "auto_refresh_owner_ids", None) or []),
        "owner_id",
    )
    qs = _apply_id_scope(
        qs,
        normalize_auto_refresh_group_ids(getattr(cfg, "auto_refresh_group_ids", None) or []),
        "group_id",
    )
    qs = _apply_id_scope(
        qs,
        normalize_auto_refresh_country_ids(getattr(cfg, "auto_refresh_country_ids", None) or []),
        "country_id",
    )
    qs = _apply_id_scope(
        qs,
        normalize_auto_refresh_domain_ids(getattr(cfg, "auto_refresh_domain_ids", None) or []),
        "domain_id",
    )
    return qs
