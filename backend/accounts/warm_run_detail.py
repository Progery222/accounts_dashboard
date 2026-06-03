"""Прогрев Facebook в run_detail для модалки очереди."""

from __future__ import annotations

from typing import Any

from django.utils import timezone

from .models import AutoRefreshState, RefreshAllState


def _active_refresh_state():
    rr = RefreshAllState.get()
    if rr.is_running:
        return rr
    auto = AutoRefreshState.get()
    if auto.is_running:
        return auto
    return None


def is_refresh_cancel_requested() -> bool:
    """Остановка из bulk_refresh, refresh_all или автообновления."""
    # Не вызывать close_old_connections() здесь: проверка идёт из transaction.atomic()
    # при сохранении аккаунта — закрытие соединения даёт «the connection is closed».
    # cancel_requested у AutoRefreshState учитываем всегда (в т.ч. после force_stop, когда
    # is_running уже False). У RefreshAllState — только пока идёт «Обновить всё», иначе
    # залипший cancel после остановки блокирует новое автообновление.
    try:
        rr = (
            RefreshAllState.objects.filter(pk=1)
            .values("is_running", "cancel_requested")
            .first()
        )
        if rr and rr.get("cancel_requested") and rr.get("is_running"):
            return True
        auto = (
            AutoRefreshState.objects.filter(pk=1)
            .values("is_running", "cancel_requested")
            .first()
        )
        if auto and auto.get("cancel_requested"):
            return True
    except Exception:
        return False
    return False


def clear_warm_run_detail(platform: str) -> None:
    """Убрать блок прогрева платформы из run_detail (прогрев выключен в настройках)."""
    st = _active_refresh_state()
    if st is None:
        return
    plat = str(platform or "").strip().lower()
    if not plat:
        return
    rd = dict(st.run_detail or {})
    warm = dict(rd.get("warm") or {})
    if plat in warm:
        del warm[plat]
    if warm:
        rd["warm"] = warm
    else:
        rd.pop("warm", None)
    st.run_detail = rd
    st.save(update_fields=["run_detail", "updated_at"])


def persist_warm_run_detail(platform: str, patch: dict[str, Any]) -> None:
    st = _active_refresh_state()
    if st is None:
        return
    plat = str(platform or "").strip().lower()
    if not plat:
        return
    rd = dict(st.run_detail or {})
    warm = dict(rd.get("warm") or {})
    prev = dict(warm.get(plat) or {})
    prev.update(patch)
    warm[plat] = prev
    rd["warm"] = warm
    st.run_detail = rd
    status = (patch.get("status") or prev.get("status") or "").strip()
    if status == "running":
        pct = int(patch.get("progress_percent") or prev.get("progress_percent") or 0)
        videos = int(patch.get("videos") or prev.get("videos") or 0)
        likes = int(patch.get("likes") or prev.get("likes") or 0)
        st.current_account = f"прогрев {plat} · {pct}% · роликов {videos} · лайков {likes}"
    elif status == "cancelled":
        st.current_account = f"прогрев {plat} · остановка…"
    elif status in {"done", "error", "skipped"}:
        if (st.current_account or "").startswith("прогрев "):
            st.current_account = ""
    st.save(update_fields=["run_detail", "current_account", "updated_at"])


def mark_warm_running(platform: str, *, min_minutes: float, max_minutes: float, detail: str = "") -> None:
    persist_warm_run_detail(
        platform,
        {
            "status": "running",
            "progress_percent": 0,
            "elapsed_sec": 0,
            "planned_sec": int(max_minutes * 60),
            "videos": 0,
            "likes": 0,
            "min_minutes": min_minutes,
            "max_minutes": max_minutes,
            "detail": detail,
            "started_at": timezone.now().isoformat(),
        },
    )


def apply_warm_progress_file(platform: str, path: str) -> None:
    from platforms.warm_progress import read_warm_progress

    data = read_warm_progress(path)
    if not data:
        return
    planned = float(data.get("planned_sec") or 0)
    elapsed = float(data.get("elapsed_sec") or 0)
    pct = int(data.get("progress_percent") or 0)
    if planned > 0:
        pct = min(99, int(round(100 * elapsed / planned)))
    st = _active_refresh_state()
    prev: dict[str, Any] = {}
    if st is not None:
        rd = dict(st.run_detail or {})
        warm = dict(rd.get("warm") or {})
        prev = dict(warm.get(platform) or {})
    if data.get("cancel_requested"):
        patch_status = "cancelled"
    else:
        patch_status = data.get("status") or "running"
    patch: dict[str, Any] = {
        "status": patch_status,
        "progress_percent": pct,
        "elapsed_sec": int(elapsed),
        "planned_sec": int(planned),
        "videos": int(data.get("videos") or 0),
        "likes": int(data.get("likes") or 0),
        "detail": str(data.get("detail") or prev.get("detail") or ""),
    }
    if prev.get("min_minutes") is not None:
        patch["min_minutes"] = prev.get("min_minutes")
    if prev.get("max_minutes") is not None:
        patch["max_minutes"] = prev.get("max_minutes")
    persist_warm_run_detail(platform, patch)


def finalize_warm_run_detail_cancelled(platform: str) -> None:
    persist_warm_run_detail(
        platform,
        {
            "status": "cancelled",
            "detail": "Остановлено пользователем",
        },
    )


def finalize_warm_run_detail(platform: str, stats: dict | None, *, error: str | None = None) -> None:
    if stats and stats.get("cancelled"):
        finalize_warm_run_detail_cancelled(platform)
        return
    if error:
        persist_warm_run_detail(
            platform,
            {
                "status": "error",
                "progress_percent": 0,
                "detail": error[:500],
            },
        )
        return
    st = stats or {}
    planned = float(st.get("planned_sec") or st.get("duration_sec") or 0)
    elapsed = float(st.get("duration_sec") or 0)
    pct = 100 if elapsed > 0 else 0
    persist_warm_run_detail(
        platform,
        {
            "status": "done",
            "progress_percent": pct,
            "elapsed_sec": int(elapsed),
            "planned_sec": int(planned or elapsed),
            "videos": int(st.get("videos") or 0),
            "likes": int(st.get("likes") or 0),
            "detail": "завершён",
        },
    )
