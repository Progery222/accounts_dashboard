"""Запись platform_deltas в AutoRefreshPoint при любом успешном refresh."""

from __future__ import annotations

import threading
from datetime import timedelta

from django.db.models import Sum
from django.utils import timezone

from .models import Account, AutoRefreshPoint, Platform

_batch_mode = threading.local()

# Инкрементальные refresh в одном окне сливаются в одну точку (platform_deltas суммируются).
MERGE_WINDOW = timedelta(minutes=45)

_INCREMENTAL_SOURCES = frozenset({"refresh", "refresh_all", "api"})


def enter_refresh_pulse_batch() -> None:
    _batch_mode.active = True


def exit_refresh_pulse_batch() -> None:
    _batch_mode.active = False


class refresh_pulse_batch:
    """Контекст: во время полного автообновления не пишем точки на каждый аккаунт."""

    def __enter__(self):
        enter_refresh_pulse_batch()
        return self

    def __exit__(self, *args):
        exit_refresh_pulse_batch()
        return False


def is_refresh_pulse_batch() -> bool:
    return bool(getattr(_batch_mode, "active", False))


def clamp_platform_view_delta(platform: str, raw: int) -> int:
    if platform in (Platform.INSTAGRAM, Platform.THREADS):
        return max(0, int(raw))
    return int(raw)


def _current_views_total() -> int:
    return int(Account.objects.aggregate(total=Sum("view_count")).get("total") or 0)


def _point_totals_at(finished, current_total: int) -> tuple[int, int]:
    local_dt = timezone.localtime(finished)
    local_date = local_dt.date()
    prev_point = (
        AutoRefreshPoint.objects.filter(measured_at__lt=finished)
        .order_by("-measured_at")
        .first()
    )
    first_today = (
        AutoRefreshPoint.objects.filter(local_date=local_date)
        .order_by("measured_at")
        .first()
    )
    prev_total = int(prev_point.view_count_total) if prev_point else current_total
    day_start_total = int(first_today.view_count_total) if first_today else current_total
    return current_total - prev_total, current_total - day_start_total


def record_account_refresh_platform_delta(
    platform: str,
    view_before: int,
    view_after: int,
    *,
    source: str = "refresh",
) -> None:
    """Одна успешная запись refresh → вклад платформы в pulse (если не batch-режим)."""
    if is_refresh_pulse_batch():
        return
    platform_key = str(platform or "").strip().lower()
    if not platform_key:
        return
    delta = clamp_platform_view_delta(
        platform_key,
        int(view_after or 0) - int(view_before or 0),
    )
    if delta == 0:
        return
    _append_platform_delta(platform_key, delta, source=source)


def _append_platform_delta(platform: str, delta: int, *, source: str) -> None:
    finished = timezone.now()
    current_total = _current_views_total()
    d_prev, d_day = _point_totals_at(finished, current_total)
    merge_from = finished - MERGE_WINDOW
    latest = (
        AutoRefreshPoint.objects.filter(measured_at__gte=merge_from)
        .order_by("-measured_at")
        .first()
    )
    if latest and str(latest.source or "") in _INCREMENTAL_SOURCES:
        pd = dict(latest.platform_deltas or {})
        pd[platform] = int(pd.get(platform, 0)) + int(delta)
        latest.platform_deltas = pd
        latest.view_count_total = current_total
        latest.view_delta_from_prev_point = d_prev
        latest.view_delta_from_day_start = d_day
        latest.save(
            update_fields=[
                "platform_deltas",
                "view_count_total",
                "view_delta_from_prev_point",
                "view_delta_from_day_start",
            ],
        )
        return

    local_dt = timezone.localtime(finished)
    AutoRefreshPoint.objects.create(
        local_date=local_dt.date(),
        source=source or "refresh",
        slot_label=local_dt.strftime("%H:%M"),
        view_count_total=current_total,
        view_delta_from_prev_point=d_prev,
        view_delta_from_day_start=d_day,
        platform_deltas={platform: int(delta)},
    )


def _to_int(v) -> int | None:
    try:
        if v is None:
            return None
        if isinstance(v, bool):
            return int(v)
        if isinstance(v, (int, float)):
            return int(v)
        s = str(v).strip()
        if not s:
            return None
        return int(float(s))
    except Exception:
        return None


def platform_deltas_from_report_rows(report_rows: list) -> dict[str, int]:
    platform_deltas: dict[str, int] = {}
    for row in report_rows or []:
        platform = str(row.get("platform") or "").strip().lower()
        if not platform:
            continue
        before_v = _to_int(row.get("view_before"))
        after_v = _to_int(row.get("view_after"))
        if before_v is None or after_v is None:
            continue
        raw = after_v - before_v
        platform_deltas[platform] = int(platform_deltas.get(platform, 0)) + clamp_platform_view_delta(
            platform, raw
        )
    return platform_deltas


def create_auto_refresh_point_from_report_rows(
    report_rows: list,
    *,
    source: str,
    finished=None,
) -> None:
    """Точка после полного прогона автообновления (все платформы из отчёта)."""
    finished = finished or timezone.now()
    platform_deltas = platform_deltas_from_report_rows(report_rows)
    current_total = _current_views_total()
    d_prev, d_day = _point_totals_at(finished, current_total)
    local_dt = timezone.localtime(finished)
    AutoRefreshPoint.objects.create(
        local_date=local_dt.date(),
        source=source or "scheduler",
        slot_label=local_dt.strftime("%H:%M"),
        view_count_total=current_total,
        view_delta_from_prev_point=d_prev,
        view_delta_from_day_start=d_day,
        platform_deltas=platform_deltas,
    )
