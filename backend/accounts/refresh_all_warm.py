"""Прогрев Facebook в том же Chromium, что и съём (refresh_all и автообновление)."""

from __future__ import annotations

import os
import random
import sys
import tempfile
import threading
from pathlib import Path

from accounts.models import Platform
from accounts.warm_run_detail import (
    apply_warm_progress_file,
    finalize_warm_run_detail,
    finalize_warm_run_detail_cancelled,
    is_refresh_cancel_requested,
    mark_warm_running,
    persist_warm_run_detail,
)

_WARM_PLATFORMS = frozenset({Platform.FACEBOOK})


def refresh_warm_enabled() -> bool:
    """Прогрев включён в настройках расписания (UI), если env не отключил жёстко."""
    for key in ("REFRESH_ALL_WARM_DISABLED", "AUTO_REFRESH_WARM_DISABLED"):
        if (os.environ.get(key) or "").strip().lower() in {"1", "true", "yes"}:
            return False
    try:
        from accounts.models import RefreshScheduleConfig

        return bool(getattr(RefreshScheduleConfig.get(), "refresh_warm_enabled", True))
    except Exception:
        return True


def facebook_parallel_warm_tab_enabled() -> bool:
    """Прогрев Reels во 2-й вкладке параллельно съёму FB (по умолчанию вкл.)."""
    return (os.environ.get("FACEBOOK_WARM_PARALLEL_TAB") or "1").strip().lower() not in {
        "0", "false", "no", "off",
    }


def facebook_parallel_warm_active() -> bool:
    """Параллельный прогрев FB: только при галочке «Прогрев» в расписании + env вкладки."""
    return refresh_warm_enabled() and facebook_parallel_warm_tab_enabled()


_WORKER_PATHS: dict[str, Path] = {
    Platform.FACEBOOK: Path(__file__).resolve().parent.parent / "platforms" / "facebook" / "worker.py",
}


def _float_env(name: str, default: float) -> float:
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


_WARM_DEFAULT_MIN_MINUTES = 3.0
_WARM_DEFAULT_MAX_MINUTES = 11.0


def warm_minutes_for_platform(platform: str) -> tuple[float, float]:
    """Длительность прогрева Facebook для фиксированного warm (legacy, не parallel)."""
    key = str(platform or "").strip().lower()
    if key == Platform.FACEBOOK:
        return (
            _float_env("REFRESH_ALL_WARM_FACEBOOK_MIN_MINUTES", _WARM_DEFAULT_MIN_MINUTES),
            _float_env("REFRESH_ALL_WARM_FACEBOOK_MAX_MINUTES", _WARM_DEFAULT_MAX_MINUTES),
        )
    return (_WARM_DEFAULT_MIN_MINUTES, _WARM_DEFAULT_MAX_MINUTES)


def warm_interval_profiles() -> int:
    lo = max(1, int(_float_env("REFRESH_ALL_WARM_EVERY_MIN", 15)))
    hi = max(lo, int(_float_env("REFRESH_ALL_WARM_EVERY_MAX", 30)))
    return random.randint(lo, hi)


def _warm_detail_for_platform(platform: str) -> str:
    if platform == Platform.FACEBOOK:
        return "Reels"
    return ""


def _facebook_worker_path() -> Path | None:
    p = _WORKER_PATHS.get(Platform.FACEBOOK)
    if p is not None and p.exists():
        return p
    return None


def start_facebook_parallel_warm(*, label: str = "refresh_all", progress_path: Path | str) -> None:
    """Запустить прогрев во 2-й вкладке; ответ worker приходит сразу, прогрев идёт в фоне демона."""
    if not facebook_parallel_warm_active():
        return
    worker_path = _facebook_worker_path()
    if worker_path is None:
        return
    plat = Platform.FACEBOOK
    print(
        f"[{label}] прогрев {plat}: Reels во 2-й вкладке, пока идёт обновление FB…",
        file=sys.stderr,
        flush=True,
    )
    from platforms.worker_pool import call_worker, ensure_worker

    mark_warm_running(
        plat,
        min_minutes=0,
        max_minutes=0,
        detail="Reels · вкладка 2",
    )
    ensure_worker(worker_path)
    call_worker(
        worker_path,
        {
            "warm_parallel": True,
            "action": "start",
            "refresh_warm_enabled": True,
            "progress_path": str(Path(progress_path).resolve()),
        },
        timeout_sec=120.0,
    )


def stop_facebook_parallel_warm(*, label: str = "refresh_all", progress_path: Path | str | None = None) -> dict:
    """Остановить фоновый прогрев и дождаться ответа worker."""
    worker_path = _facebook_worker_path()
    if worker_path is None:
        return {}
    plat = Platform.FACEBOOK
    if progress_path is not None:
        try:
            from platforms.warm_progress import write_warm_progress

            write_warm_progress(
                progress_path,
                platform=plat,
                cancel_requested=True,
                status="cancelled",
            )
        except Exception:
            pass
    from platforms.worker_pool import call_worker

    try:
        stats = call_worker(
            worker_path,
            {"warm_parallel": True, "action": "stop"},
            timeout_sec=90.0,
        )
    except Exception as exc:
        print(f"[{label}] остановка прогрева {plat}: {exc}", file=sys.stderr, flush=True)
        finalize_warm_run_detail_cancelled(plat)
        return {}
    if stats.get("cancelled") or is_refresh_cancel_requested():
        finalize_warm_run_detail_cancelled(plat)
    else:
        finalize_warm_run_detail(plat, stats)
    print(
        f"[{label}] прогрев {plat} (вкладка 2) завершён: "
        f"videos={stats.get('videos', 0)} likes={stats.get('likes', 0)} "
        f"duration_sec={stats.get('duration_sec', 0):.0f}",
        file=sys.stderr,
        flush=True,
    )
    return stats


def run_refresh_all_warm(platform: str, *, label: str = "refresh_all") -> None:
    """Фиксированный прогрев в одной вкладке (legacy, между пачками профилей)."""
    if not refresh_warm_enabled():
        return
    if is_refresh_cancel_requested():
        finalize_warm_run_detail_cancelled(str(platform or "").strip().lower())
        return
    plat = str(platform or "").strip().lower()
    if plat not in _WARM_PLATFORMS:
        return
    worker_path = _WORKER_PATHS.get(plat)
    if worker_path is None or not worker_path.exists():
        return
    lo, hi = warm_minutes_for_platform(plat)
    max_m = max(lo, hi)
    payload = {
        "warm": True,
        "refresh_warm_enabled": True,
        "min_minutes": lo,
        "max_minutes": max_m,
    }
    timeout_sec = max(900.0, float(max_m) * 60.0 + 120.0)
    print(
        f"[{label}] прогрев {plat}: ~{lo:.0f}–{max_m:.0f} мин "
        f"в окне worker…",
        file=sys.stderr,
        flush=True,
    )
    from platforms.warm_progress import read_warm_progress, write_warm_progress
    from platforms.worker_pool import call_worker, ensure_worker, release_worker

    mark_warm_running(plat, min_minutes=lo, max_minutes=max_m, detail=_warm_detail_for_platform(plat))

    fd, progress_path = tempfile.mkstemp(prefix=f"warm-{plat}-", suffix=".json")
    os.close(fd)
    progress_file = Path(progress_path)
    payload["progress_path"] = str(progress_file.resolve())

    stop_poll = threading.Event()

    def _poll_progress_and_cancel() -> None:
        while not stop_poll.is_set():
            if is_refresh_cancel_requested():
                try:
                    write_warm_progress(
                        progress_file,
                        platform=plat,
                        cancel_requested=True,
                        status="cancelled",
                    )
                    apply_warm_progress_file(plat, str(progress_file))
                except Exception:
                    pass
                try:
                    release_worker(worker_path)
                except Exception:
                    pass
                stop_poll.set()
                return
            try:
                apply_warm_progress_file(plat, str(progress_file))
            except Exception:
                pass
            stop_poll.wait(1.0)

    poll_thread = threading.Thread(
        target=_poll_progress_and_cancel,
        daemon=True,
        name=f"warm-poll-{plat}",
    )
    poll_thread.start()

    ensure_worker(worker_path)
    cancelled = False
    try:
        stats = call_worker(worker_path, payload, timeout_sec=timeout_sec)
        file_data = read_warm_progress(progress_file)
        if file_data.get("cancel_requested") or is_refresh_cancel_requested():
            cancelled = True
        elif file_data.get("planned_sec"):
            stats = {**stats, "planned_sec": file_data["planned_sec"]}
        if stats.get("cancelled"):
            cancelled = True
        if cancelled:
            print(f"[{label}] прогрев {plat} остановлен пользователем", file=sys.stderr, flush=True)
            finalize_warm_run_detail_cancelled(plat)
            return
        print(
            f"[{label}] прогрев {plat} завершён: "
            f"videos={stats.get('videos', 0)} likes={stats.get('likes', 0)} "
            f"duration_sec={stats.get('duration_sec', 0):.0f}",
            file=sys.stderr,
            flush=True,
        )
        finalize_warm_run_detail(plat, stats)
    except Exception as exc:
        if is_refresh_cancel_requested() or read_warm_progress(progress_file).get("cancel_requested"):
            print(f"[{label}] прогрев {plat} остановлен пользователем", file=sys.stderr, flush=True)
            finalize_warm_run_detail_cancelled(plat)
        else:
            print(f"[{label}] прогрев {plat} не удался: {exc}", file=sys.stderr, flush=True)
            finalize_warm_run_detail(plat, None, error=str(exc))
    finally:
        stop_poll.set()
        poll_thread.join(timeout=4.0)
        try:
            apply_warm_progress_file(plat, str(progress_file))
        except Exception:
            pass
        try:
            progress_file.unlink(missing_ok=True)
        except Exception:
            pass


class RefreshAllWarmTracker:
    """
    Facebook: прогрев Reels во 2-й вкладке параллельно съёму (пока не кончатся FB-аккаунты в прогоне).
    Legacy (FACEBOOK_WARM_PARALLEL_TAB=0): блокирующий прогрев в начале + каждые N профилей.
    """

    def __init__(self, accounts: list, *, label: str = "refresh_all") -> None:
        self._label = (label or "refresh_all").strip() or "refresh_all"
        self._lock = threading.Lock()
        self._counts: dict[str, int] = {Platform.FACEBOOK: 0}
        self._next_at: dict[str, int] = {Platform.FACEBOOK: warm_interval_profiles()}
        self._fb_ready = threading.Event()
        self._warm_threads: list[threading.Thread] = []
        self._parallel_fb_warm = False
        self._parallel_warm_stop = threading.Event()
        self._parallel_progress_file: Path | None = None

        has_fb = any(getattr(a, "platform", None) == Platform.FACEBOOK for a in accounts)
        warm_on = refresh_warm_enabled() and not is_refresh_cancel_requested()

        if not warm_on or not has_fb:
            if has_fb and not warm_on:
                from accounts.warm_run_detail import clear_warm_run_detail

                clear_warm_run_detail(Platform.FACEBOOK)
            self._fb_ready.set()
            return

        if facebook_parallel_warm_active():
            self._parallel_fb_warm = True
            self._fb_ready.set()
            fd, progress_path = tempfile.mkstemp(prefix="warm-facebook-parallel-", suffix=".json")
            os.close(fd)
            self._parallel_progress_file = Path(progress_path)
            persist_warm_run_detail(
                Platform.FACEBOOK,
                {
                    "status": "queued",
                    "progress_percent": 0,
                    "elapsed_sec": 0,
                    "planned_sec": 0,
                    "videos": 0,
                    "likes": 0,
                    "min_minutes": 0,
                    "max_minutes": 0,
                    "detail": "Reels · вкладка 2",
                },
            )

            def _parallel_warm_loop() -> None:
                try:
                    start_facebook_parallel_warm(
                        label=self._label,
                        progress_path=self._parallel_progress_file,
                    )
                    while not self._parallel_warm_stop.is_set():
                        if is_refresh_cancel_requested():
                            break
                        try:
                            apply_warm_progress_file(
                                Platform.FACEBOOK,
                                str(self._parallel_progress_file),
                            )
                        except Exception:
                            pass
                        self._parallel_warm_stop.wait(1.0)
                except Exception as exc:
                    print(
                        f"[{self._label}] параллельный прогрев facebook не запустился: {exc}",
                        file=sys.stderr,
                        flush=True,
                    )
                    finalize_warm_run_detail(Platform.FACEBOOK, None, error=str(exc))
                finally:
                    try:
                        stop_facebook_parallel_warm(
                            label=self._label,
                            progress_path=self._parallel_progress_file,
                        )
                    except Exception as exc:
                        print(
                            f"[{self._label}] остановка параллельного прогрева facebook: {exc}",
                            file=sys.stderr,
                            flush=True,
                        )
                    try:
                        if self._parallel_progress_file is not None:
                            self._parallel_progress_file.unlink(missing_ok=True)
                    except Exception:
                        pass

            th = threading.Thread(
                target=_parallel_warm_loop,
                name=f"warm-facebook-parallel-{self._label}",
                daemon=True,
            )
            th.start()
            self._warm_threads.append(th)
            return

        lo, hi = warm_minutes_for_platform(Platform.FACEBOOK)
        persist_warm_run_detail(
            Platform.FACEBOOK,
            {
                "status": "queued",
                "progress_percent": 0,
                "elapsed_sec": 0,
                "planned_sec": 0,
                "videos": 0,
                "likes": 0,
                "min_minutes": lo,
                "max_minutes": hi,
                "detail": _warm_detail_for_platform(Platform.FACEBOOK),
            },
        )

        def _warm_fb() -> None:
            try:
                run_refresh_all_warm(Platform.FACEBOOK, label=self._label)
            finally:
                self._fb_ready.set()

        th = threading.Thread(target=_warm_fb, name=f"warm-facebook-{self._label}", daemon=True)
        th.start()
        self._warm_threads.append(th)

    def wait_warm_before_refresh(self, platform: str) -> None:
        """При parallel tab FB не ждёт; legacy — ждёт завершения стартового warm."""
        if str(platform or "").strip().lower() == Platform.FACEBOOK and not self._parallel_fb_warm:
            while not self._fb_ready.is_set():
                if is_refresh_cancel_requested():
                    return
                self._fb_ready.wait(timeout=1.0)

    def join_warm_threads(self, timeout: float | None = None) -> None:
        if self._parallel_fb_warm:
            self._parallel_warm_stop.set()
        per = None if timeout is None else max(1.0, timeout / max(1, len(self._warm_threads)))
        for th in self._warm_threads:
            th.join(timeout=per)

    def after_network_refresh(self, platform: str, *, label: str | None = None) -> None:
        if self._parallel_fb_warm:
            return
        plat = str(platform or "").strip().lower()
        if plat not in _WARM_PLATFORMS:
            return
        log_label = (label or self._label).strip() or self._label
        with self._lock:
            self._counts[plat] = self._counts.get(plat, 0) + 1
            if self._counts[plat] < self._next_at[plat]:
                return
            self._counts[plat] = 0
            self._next_at[plat] = warm_interval_profiles()
            n = self._next_at[plat]
        print(
            f"[{log_label}] {plat}: порог прогрева — снова warm (следующий через {n} профилей)",
            file=sys.stderr,
            flush=True,
        )
        if not is_refresh_cancel_requested():
            run_refresh_all_warm(plat, label=log_label)
