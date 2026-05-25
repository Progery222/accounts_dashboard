"""Сброс зависшего is_running после сбоя, warm_tiktok_session или перезапуска Django."""

from __future__ import annotations

import os
from datetime import timedelta

from django.utils import timezone


def _float_env(name: str, default: float) -> float:
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _state_looks_stale(state, *, stale_hours: float, stall_hours: float) -> bool:
    if not getattr(state, "is_running", False):
        return False
    now = timezone.now()
    started = getattr(state, "started_at", None)
    updated = getattr(state, "updated_at", None) or started
    if started and (now - started) > timedelta(hours=max(0.5, stale_hours)):
        return True
    if updated and (now - updated) > timedelta(hours=max(0.25, stall_hours)):
        return True
    return False


def clear_stuck_refresh_run(
    *,
    reason: str,
    models: tuple[str, ...] = ("auto", "refresh_all"),
) -> list[str]:
    """
    Принудительно снять is_running (после warm_tiktok / kill workers / падение потока).
    Возвращает список сброшенных: auto, refresh_all.
    """
    from .models import AutoRefreshState, RefreshAllState

    cleared: list[str] = []
    now = timezone.now()
    for key, model in (("auto", AutoRefreshState), ("refresh_all", RefreshAllState)):
        if key not in models:
            continue
        st = model.get()
        if not st.is_running:
            continue
        st.is_running = False
        st.cancel_requested = False
        st.current_account = ""
        st.last_error = (reason or "")[:500]
        if not st.finished_at:
            st.finished_at = now
        st.save(
            update_fields=[
                "is_running",
                "cancel_requested",
                "current_account",
                "last_error",
                "finished_at",
                "updated_at",
            ],
        )
        cleared.append(key)
    return cleared


def clear_abandoned_cancelled_runs(*, max_minutes: float = 8.0) -> list[str]:
    """После «Остановить» поток мог зависнуть на call_worker — снять is_running."""
    from .models import AutoRefreshState, RefreshAllState

    cleared: list[str] = []
    now = timezone.now()
    for key, model in (("auto", AutoRefreshState), ("refresh_all", RefreshAllState)):
        st = model.get()
        if not st.is_running or not st.cancel_requested:
            continue
        ref = st.updated_at or st.started_at
        if ref and (now - ref) <= timedelta(minutes=max(1.0, max_minutes)):
            continue
        cleared.extend(
            clear_stuck_refresh_run(
                reason="Прогон сброшен после остановки (поток не завершился).",
                models=(key,),
            ),
        )
    return cleared


def clear_stale_refresh_runs_if_needed() -> list[str]:
    """Сбросить зависшие прогоны: долгий простой, отмена без завершения, общий таймаут."""
    from .models import AutoRefreshState, RefreshAllState

    stale_h = _float_env("AUTO_REFRESH_STALE_HOURS", 14.0)
    stall_h = _float_env("AUTO_REFRESH_STALL_HOURS", 4.0)
    cleared: list[str] = []
    cleared.extend(clear_abandoned_cancelled_runs())
    for key, model in (("auto", AutoRefreshState), ("refresh_all", RefreshAllState)):
        if key in cleared:
            continue
        st = model.get()
        if _state_looks_stale(st, stale_hours=stale_h, stall_hours=stall_h):
            msg = (
                f"Прогон сброшен: нет активности > {stall_h:g} ч "
                f"(или длительность > {stale_h:g} ч). Можно запустить снова."
            )
            part = clear_stuck_refresh_run(reason=msg, models=(key,))
            cleared.extend(part)
    return cleared
