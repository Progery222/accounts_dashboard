"""Сброс зависшего is_running после сбоя, warm_tiktok_session или перезапуска Django."""

from __future__ import annotations

import os
import sys
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
    finished = getattr(state, "finished_at", None)
    # Активный прогон: не сбрасывать по «старому» started_at до обновления в теле run.
    if finished is None and started and (now - started) <= timedelta(hours=1):
        stall_hours = max(stall_hours, 6.0)
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


def finalize_auto_refresh_run_detail_cancelled() -> None:
    """Пометить queued/running в run_detail как cancelled (после «Остановить»)."""
    from django.db import transaction

    from .models import AutoRefreshState

    try:
        with transaction.atomic():
            st = AutoRefreshState.objects.select_for_update().get(pk=1)
            rd = dict(st.run_detail or {})
            items = [dict(x) for x in (rd.get("items") or [])]
            changed = False
            for it in items:
                stt = str(it.get("status") or "")
                if stt in ("queued", "running"):
                    it["status"] = "cancelled"
                    it["detail"] = "не обработан (остановка или прерывание)"
                    it["worker"] = None
                    changed = True
            if changed:
                rd["items"] = items
                st.run_detail = rd
                st.save(update_fields=["run_detail", "updated_at"])
    except Exception as exc:
        print(f"[refresh_state] finalize run_detail cancelled failed: {exc}", file=sys.stderr)


def force_stop_auto_refresh(*, reason: str = "Остановлено пользователем.") -> None:
    """Сбросить UI сразу; флаг cancel_requested держим до выхода потока scheduled_refresh."""
    import sys
    import threading

    from .models import AutoRefreshState, RefreshAllState

    now = timezone.now()
    msg = (reason or "")[:500]

    auto = AutoRefreshState.get()
    if not auto.is_running and not auto.cancel_requested:
        auto = None
    else:
        auto.cancel_requested = True
        finalize_auto_refresh_run_detail_cancelled()
        auto.is_running = False
        auto.current_account = ""
        if not auto.finished_at:
            auto.finished_at = now
        auto.last_error = msg
        auto.save(
            update_fields=[
                "cancel_requested",
                "is_running",
                "current_account",
                "finished_at",
                "last_error",
                "updated_at",
            ],
        )

    rr = RefreshAllState.get()
    if rr.is_running:
        rr.cancel_requested = True
        rr.save(update_fields=["cancel_requested", "updated_at"])

    if auto is None and not rr.is_running:
        return

    def _interrupt_workers() -> None:
        try:
            from .refresh_interrupt import interrupt_refresh_playwright_workers

            interrupt_refresh_playwright_workers(label="auto_refresh_force_stop")
        except Exception as exc:
            print(f"[auto_refresh_force_stop] interrupt failed: {exc}", file=sys.stderr)

    threading.Thread(target=_interrupt_workers, daemon=True, name="refresh-force-stop").start()


def clear_orphan_cancel_flags() -> None:
    """После force_stop поток мог умереть, оставив cancel_requested=True при is_running=False."""
    from .models import AutoRefreshState, RefreshAllState

    for model in (AutoRefreshState, RefreshAllState):
        st = model.get()
        if st.is_running or not st.cancel_requested:
            continue
        st.cancel_requested = False
        st.save(update_fields=["cancel_requested", "updated_at"])


def clear_stale_refresh_runs_if_needed() -> list[str]:
    """Сбросить зависшие прогоны: долгий простой, отмена без завершения, общий таймаут."""
    from .models import AutoRefreshState, RefreshAllState

    stale_h = _float_env("AUTO_REFRESH_STALE_HOURS", 14.0)
    stall_h = _float_env("AUTO_REFRESH_STALL_HOURS", 4.0)
    cleared: list[str] = []
    clear_orphan_cancel_flags()
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
