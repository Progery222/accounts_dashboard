"""Порядок очереди массового / автообновления аккаунтов."""
from __future__ import annotations

from datetime import datetime

from django.db.models import F, QuerySet
from django.utils import timezone

from .models import Account


def queryset_order_by_staleness(qs: QuerySet[Account]) -> QuerySet[Account]:
    """Сначала давно не обновлявшиеся (updated_at ↑), затем id."""
    return qs.order_by(F("updated_at").asc(nulls_first=True), "id")


def _staleness_sort_key(account: Account) -> datetime:
    ts = account.updated_at
    if ts is not None:
        return ts
    if timezone.is_aware(timezone.now()):
        return timezone.make_aware(datetime.min)
    return datetime.min


def sort_accounts_by_staleness(items: list[Account]) -> list[Account]:
    return sorted(items, key=_staleness_sort_key)


def interleave_accounts_by_platform(items: list[Account]) -> list[Account]:
    """
    Round-robin по платформам, чтобы одна платформа не блокировала всю очередь.
    Внутри платформы порядок элементов в buckets сохраняется (ожидается: по давности).
    """
    buckets: dict[str, list[Account]] = {}
    platform_order: list[str] = []
    for acc in items:
        p = str(acc.platform)
        if p not in buckets:
            buckets[p] = []
            platform_order.append(p)
        buckets[p].append(acc)
    out: list[Account] = []
    while True:
        pushed = False
        for p in platform_order:
            arr = buckets.get(p) or []
            if arr:
                out.append(arr.pop(0))
                pushed = True
        if not pushed:
            break
    return out


def order_accounts_for_refresh(items: list[Account]) -> list[Account]:
    """Давно не обновлённые первыми, с чередованием платформ."""
    return interleave_accounts_by_platform(sort_accounts_by_staleness(items))
