import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from zoneinfo import ZoneInfo

from django.apps import AppConfig
from django.db import transaction
from django.db.models import Sum

# Единая таймзона для Cron/Interval (иначе на UTC-хосте «03:00» nightly = 06:00 МСК).
SCHEDULER_TZ = ZoneInfo("Europe/Moscow")

_scheduler = None
_auto_refresh_lock = threading.Lock()
_queued_refresh_lock = threading.Lock()
_queued_refresh_requested = False
_queued_refresh_source = "scheduler"
_queued_refresh_fast_start = False


def get_scheduler():
    return _scheduler


def schedule_jobs_signature(config) -> tuple:
    """Поля, от которых зависит набор зарегистрированных auto_refresh_* задач."""
    enabled = bool(getattr(config, "enabled", False))
    mode = str(getattr(config, "mode", "") or "")
    if mode == "times":
        times = tuple(
            str(t).strip()
            for t in (getattr(config, "times", None) or [])
            if str(t).strip()
        )
        return (enabled, mode, times, 0)
    interval = max(1, min(24, int(getattr(config, "interval_hours", 6) or 6)))
    return (enabled, mode, (), interval)


def apply_schedule_config(config, sched):
    """Apply RefreshScheduleConfig to a running APScheduler instance."""
    from apscheduler.triggers.cron import CronTrigger
    from apscheduler.triggers.interval import IntervalTrigger

    # Remove all previously user-scheduled auto-refresh jobs
    for job in list(sched.get_jobs()):
        if job.id.startswith("auto_refresh_"):
            try:
                sched.remove_job(job.id)
            except Exception:
                pass

    if not config.enabled:
        return

    if config.mode == "interval" and config.interval_hours >= 1:
        sched.add_job(
            _scheduled_refresh,
            IntervalTrigger(hours=config.interval_hours, timezone=SCHEDULER_TZ),
            id="auto_refresh_interval",
            replace_existing=True,
        )
    elif config.mode == "times":
        for i, t in enumerate(config.times):
            try:
                h, m = map(int, t.split(":"))
                sched.add_job(
                    _scheduled_refresh,
                    CronTrigger(hour=h, minute=m, timezone=SCHEDULER_TZ),
                    id=f"auto_refresh_time_{i}",
                    replace_existing=True,
                )
            except Exception as e:
                print(f"[scheduler] invalid time slot {t!r}: {e}")


_TRUE = frozenset({"1", "true", "yes", "on", "y"})
_FALSE = frozenset({"0", "false", "no", "off", "n"})


def _scheduler_enabled_from_env() -> bool:
    """
    Включать ли scheduler в этом процессе.

    На проде под gunicorn с N воркерами scheduler стартует в каждом воркере,
    что приводит к дублям задач. Управляем явным env:

      • RUN_SCHEDULER=true  — стартовать (например, в отдельном процессе
        gunicorn --workers 1 или management-команде).
      • RUN_SCHEDULER=false — не стартовать (для остальных gunicorn-воркеров).

    Если переменная не задана — поведение как раньше: стартовать.
    """
    raw = os.environ.get("RUN_SCHEDULER")
    if raw is None:
        return True
    s = raw.strip().lower()
    if s in _TRUE:
        return True
    if s in _FALSE:
        return False
    return True


class AccountsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "accounts"

    def ready(self):
        if "runserver" in sys.argv and os.environ.get("RUN_MAIN") != "true":
            return
        # При management-командах (migrate, makemigrations, test, ...) scheduler
        # не нужен — может мешать миграциям и валить тесты.
        if any(a in sys.argv for a in (
            "migrate", "makemigrations", "collectstatic", "shell",
            "test", "createsuperuser", "loaddata", "dumpdata",
        )):
            return
        if not _scheduler_enabled_from_env():
            print("[scheduler] disabled via RUN_SCHEDULER env")
            return
        self._start_scheduler()

    def _start_scheduler(self):
        global _scheduler
        try:
            from apscheduler.schedulers.background import BackgroundScheduler
            from apscheduler.triggers.cron import CronTrigger
            from .models import AutoRefreshState, RefreshAllState

            _scheduler = BackgroundScheduler(timezone=SCHEDULER_TZ)
            # If process was restarted in the middle of an auto-refresh run, mark
            # previous run as interrupted so UI doesn't show stale "running" forever.
            try:
                state = AutoRefreshState.get()
                if state.is_running:
                    state.is_running = False
                    state.current_account = ""
                    state.last_error = "Автообновление было прервано перезапуском процесса."
                    state.save(update_fields=["is_running", "current_account", "last_error", "updated_at"])
            except Exception:
                pass
            try:
                rr = RefreshAllState.get()
                if rr.is_running:
                    rr.is_running = False
                    rr.current_account = ""
                    rr.last_error = "Сбор всех аккаунтов был прерван перезапуском процесса."
                    rr.save(update_fields=["is_running", "current_account", "last_error", "updated_at"])
            except Exception:
                pass

            # Fixed nightly refresh at 03:00 Moscow — always present
            _scheduler.add_job(
                _scheduled_refresh,
                CronTrigger(hour=3, minute=0, timezone=SCHEDULER_TZ),
                id="daily_refresh_03",
                replace_existing=True,
            )
            _scheduler.add_job(
                _scheduled_audience_refresh,
                CronTrigger(hour=4, minute=15, timezone=SCHEDULER_TZ),
                id="daily_audience_0415",
                replace_existing=True,
            )

            # Apply user-configured schedule (DB must be migrated already)
            try:
                from .models import RefreshScheduleConfig
                apply_schedule_config(RefreshScheduleConfig.get(), _scheduler)
            except Exception as e:
                print(f"[scheduler] could not load user schedule: {e}")

            _scheduler.start()
            print("[scheduler] started")
        except Exception as e:
            print(f"[scheduler] failed to start: {e}")


def _scheduled_refresh(*, source: str = "scheduler", fast_start: bool = False):
    global _queued_refresh_requested, _queued_refresh_source, _queued_refresh_fast_start
    from django.utils import timezone
    from .auto_refresh_csv import build_auto_refresh_report_csv
    from .models import (
        Account,
        AutoRefreshPoint,
        AutoRefreshState,
        RefreshAllState,
        RefreshScheduleConfig,
        GlobalVisibilityConfig,
    )
    from .views import (
        _apply_refresh,
        _apply_visibility_filters,
        _mark_profile_unavailable_if_applicable,
        _prewarm_workers,
        _refresh_all_delay_seconds,
    )

    if not _auto_refresh_lock.acquire(blocking=False):
        # If a slot fires while a run is active, queue exactly one follow-up run
        # so scheduled times are not silently lost.
        with _queued_refresh_lock:
            _queued_refresh_requested = True
            _queued_refresh_source = source or "scheduler"
            _queued_refresh_fast_start = bool(_queued_refresh_fast_start or fast_start)
        return

    try:
        if RefreshAllState.get().is_running:
            _auto_refresh_lock.release()
            return
    except Exception:
        pass

    cfg = RefreshScheduleConfig.get()
    # Свежая строка из БД: иначе при «Запустить сейчас» после POST расписания
    # теоретически возможна устаревшая копия синглтона в том же процессе.
    try:
        cfg.refresh_from_db(
            fields=[
                "skip_recent_hours",
                "enabled",
                "mode",
                "interval_hours",
                "times",
                "include_hidden_platform_accounts",
                "include_hidden_profile_accounts",
                "include_unavailable_accounts",
                "auto_refresh_csv_report",
            ],
        )
    except Exception:
        pass
    skip_recent_hours = max(0, int(getattr(cfg, "skip_recent_hours", 0) or 0))
    cutoff = timezone.now() - timedelta(hours=skip_recent_hours) if skip_recent_hours > 0 else None
    accounts_qs = Account.objects.select_related("profile").all()
    hidden_platforms = set()
    if not bool(getattr(cfg, "include_hidden_platform_accounts", False)):
        try:
            hidden_platforms = {
                str(v).strip().lower()
                for v in (GlobalVisibilityConfig.get().hidden_platforms or [])
                if str(v).strip()
            }
        except Exception:
            hidden_platforms = set()
        if hidden_platforms:
            accounts_qs = accounts_qs.exclude(platform__in=hidden_platforms)
    if not bool(getattr(cfg, "include_hidden_profile_accounts", False)):
        accounts_qs = accounts_qs.exclude(profile__is_hidden=True)
    if not bool(getattr(cfg, "include_unavailable_accounts", False)):
        accounts_qs = accounts_qs.exclude(profile_unavailable=True)
    accounts = list(accounts_qs)

    def _interleave_accounts_by_platform(items: list) -> list:
        """
        Round-robin queue by platform to avoid head-of-line blocking
        when many same-platform accounts are adjacent.
        """
        buckets: dict[str, list] = {}
        platform_order: list[str] = []
        for acc in items:
            p = str(acc.platform)
            if p not in buckets:
                buckets[p] = []
                platform_order.append(p)
            buckets[p].append(acc)
        out: list = []
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

    accounts = _interleave_accounts_by_platform(accounts)
    # Как в refresh_all: заранее поднять daemon Playwright по каждой платформе в батче.
    # Иначе Instagram с Instaloader bulk часто не открывает Chromium до поздних шагов,
    # а пользователь видит только первое окно (часто TikTok).
    try:
        _prewarm_workers(accounts)
    except Exception as e:
        print(f"[scheduled_refresh] prewarm workers failed: {e}")

    report_rows: list[dict] = []
    state = AutoRefreshState.get()
    state.is_running = True
    state.source = source
    state.cancel_requested = False
    state.total_accounts = len(accounts)
    state.processed_accounts = 0
    state.success_accounts = 0
    state.failed_accounts = 0
    state.current_account = ""
    state.last_error = ""
    state.started_at = timezone.now()
    state.finished_at = None
    state.run_detail = {}
    state.save(update_fields=[
        "is_running", "source", "cancel_requested", "total_accounts", "processed_accounts",
        "success_accounts", "failed_accounts", "current_account",
        "last_error", "started_at", "finished_at", "run_detail", "updated_at",
    ])

    ig_preload: dict[str, dict] = {}
    ig_accounts = [a for a in accounts if a.platform == "instagram"]
    if (not fast_start) and len(ig_accounts) > 1:
        try:
            from platforms.instagram.scraper import fetch_instagram_profiles_bulk

            ig_preload = fetch_instagram_profiles_bulk([a.username for a in ig_accounts])
        except Exception as e:
            print(f"[scheduled_refresh] instagram bulk preload failed: {e}")

    def _int_env(name: str, default: int, *, min_v: int = 1, max_v: int = 32) -> int:
        raw = os.environ.get(name)
        if raw is None:
            return default
        try:
            val = int(str(raw).strip())
        except Exception:
            return default
        return max(min_v, min(max_v, val))

    def _platform_limits() -> dict[str, int]:
        # Conservative defaults for anti-bot-sensitive platforms.
        defaults: dict[str, int] = {
            "tiktok": 1,
            "instagram": 1,
            "threads": 1,
            "facebook": 1,
            "rumble": 1,
            "telegram": 2,
            "x": 2,
            "reddit": 2,
            "youtube": 2,
        }
        limits: dict[str, int] = {}
        for p in {a.platform for a in accounts}:
            env_key = f"AUTO_REFRESH_CONCURRENCY_{str(p).upper()}"
            limits[p] = _int_env(env_key, defaults.get(p, 1), min_v=1, max_v=8)
        return limits

    def _profile_name(account) -> str:
        if getattr(account, "profile_id", None) and getattr(account, "profile", None):
            return account.profile.name or ""
        return "Без профиля"

    def _empty_metrics_row(account, status: str, detail: str) -> dict:
        return {
            "platform": account.platform,
            "username": account.username,
            "profile_name": _profile_name(account),
            "status": status,
            "follower_before": "",
            "follower_after": "",
            "like_before": "",
            "like_after": "",
            "view_before": "",
            "view_after": "",
            "post_before": "",
            "post_after": "",
            "elapsed_sec": "",
            "detail": detail,
        }

    try:
        queue_lock = threading.Lock()
        state_lock = threading.Lock()
        cooldown_lock = threading.Lock()
        stop_requested = threading.Event()
        next_idx = 0
        report_by_index: list[dict | None] = [None] * len(accounts)
        platform_limits = _platform_limits()
        platform_semaphores = {
            p: threading.BoundedSemaphore(value=max(1, int(v)))
            for p, v in platform_limits.items()
        }
        platform_next_allowed_at = {p: 0.0 for p in platform_limits.keys()}
        worker_count = _int_env("AUTO_REFRESH_WORKERS", 4, min_v=1, max_v=16)

        thread_slot_map: dict[int, int] = {}
        thread_slot_lock = threading.Lock()

        def _worker_slot() -> int:
            tid = threading.get_ident()
            with thread_slot_lock:
                if tid not in thread_slot_map:
                    thread_slot_map[tid] = len(thread_slot_map) % max(1, worker_count)
                return thread_slot_map[tid]

        def _persist_run_item(account_id: int, **kwargs) -> None:
            try:
                with transaction.atomic():
                    st = AutoRefreshState.objects.select_for_update().get(pk=1)
                    rd = dict(st.run_detail or {})
                    items = [dict(x) for x in (rd.get("items") or [])]
                    aid = int(account_id)
                    for i, it in enumerate(items):
                        if int(it.get("account_id", -1)) != aid:
                            continue
                        items[i] = {**it, **kwargs}
                        break
                    rd["items"] = items
                    st.run_detail = rd
                    st.save(update_fields=["run_detail", "updated_at"])
            except Exception as e:
                print(f"[scheduled_refresh] run_detail update failed for {account_id}: {e}")

        run_items = [
            {
                "account_id": a.id,
                "platform": a.platform,
                "username": a.username,
                "status": "queued",
                "worker": None,
                "detail": "",
            }
            for a in accounts
        ]
        st_plan = AutoRefreshState.objects.get(pk=1)
        st_plan.run_detail = {"items": run_items, "worker_count": worker_count}
        st_plan.save(update_fields=["run_detail", "updated_at"])

        def _finalize_run_detail_stale() -> None:
            """После остановки: аккаунты в очереди или «зависшие» в running помечаем отменёнными."""
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
            except Exception as e:
                print(f"[scheduled_refresh] run_detail finalize failed: {e}")

        def _claim_index() -> int | None:
            nonlocal next_idx
            with queue_lock:
                if next_idx >= len(accounts):
                    return None
                idx = next_idx
                next_idx += 1
                return idx

        def _mark_progress(*, success: bool, failed: bool, last_error: str = "") -> None:
            with state_lock:
                state.processed_accounts += 1
                if success:
                    state.success_accounts += 1
                if failed:
                    state.failed_accounts += 1
                    state.last_error = last_error
                state.save(update_fields=[
                    "processed_accounts", "success_accounts", "failed_accounts",
                    "last_error", "updated_at",
                ])

        def _worker() -> None:
            while True:
                idx = _claim_index()
                if idx is None:
                    return
                account = accounts[idx]
                row_started = time.perf_counter()

                if stop_requested.is_set():
                    # Hard-stop mode: do not continue queued accounts.
                    return

                with state_lock:
                    state.refresh_from_db(fields=["cancel_requested"])
                    cancelled = bool(state.cancel_requested)
                    if cancelled:
                        state.last_error = "Автообновление остановлено пользователем."
                        state.save(update_fields=["last_error", "updated_at"])
                if cancelled:
                    stop_requested.set()
                    # Hard-stop mode: stop worker immediately.
                    return

                platform_sem = platform_semaphores.get(account.platform)
                attempted_network = False
                if platform_sem is None:
                    platform_sem = threading.BoundedSemaphore(value=1)
                    platform_semaphores[account.platform] = platform_sem
                    with cooldown_lock:
                        platform_next_allowed_at.setdefault(account.platform, 0.0)

                with platform_sem:
                    while True:
                        if stop_requested.is_set():
                            return
                        with state_lock:
                            state.refresh_from_db(fields=["cancel_requested"])
                            if bool(state.cancel_requested):
                                state.last_error = "Автообновление остановлено пользователем."
                                state.save(update_fields=["last_error", "updated_at"])
                                stop_requested.set()
                                return
                        with cooldown_lock:
                            wait_sec = platform_next_allowed_at.get(account.platform, 0.0) - time.monotonic()
                        if wait_sec <= 0:
                            break
                        time.sleep(min(0.2, wait_sec))

                    slot = _worker_slot()
                    with state_lock:
                        state.current_account = f"{account.platform}/@{account.username}"
                        state.save(update_fields=["current_account", "updated_at"])
                    _persist_run_item(account.id, status="running", worker=slot)

                    before = None
                    try:
                        if stop_requested.is_set():
                            return
                        if cutoff is not None and account.updated_at and account.updated_at >= cutoff:
                            account.refresh_from_db()
                            fb = int(account.follower_count or 0)
                            lb = int(account.like_count or 0)
                            vb = int(account.view_count or 0)
                            pb = int(account.post_count or 0)
                            report_by_index[idx] = {
                                "platform": account.platform,
                                "username": account.username,
                                "profile_name": _profile_name(account),
                                "status": "пропущен",
                                "follower_before": fb,
                                "follower_after": fb,
                                "like_before": lb,
                                "like_after": lb,
                                "view_before": vb,
                                "view_after": vb,
                                "post_before": pb,
                                "post_after": pb,
                                "elapsed_sec": round(max(0.0, time.perf_counter() - row_started), 3),
                                "detail": f"недавно обновлён (≤ {skip_recent_hours} ч)",
                            }
                            _mark_progress(success=True, failed=False)
                            _persist_run_item(
                                account.id,
                                status="skipped",
                                worker=None,
                                detail=f"недавно обновлён (≤ {skip_recent_hours} ч)",
                            )
                            continue

                        account.refresh_from_db()
                        before = (
                            int(account.follower_count or 0),
                            int(account.like_count or 0),
                            int(account.view_count or 0),
                            int(account.post_count or 0),
                        )
                        scraped = None
                        if account.platform == "instagram" and ig_preload:
                            key = (account.username or "").lstrip("@").strip().lower()
                            scraped = ig_preload.get(key)
                        attempted_network = True
                        _apply_refresh(account, scraped=scraped)
                        account.refresh_from_db()
                        after = (
                            int(account.follower_count or 0),
                            int(account.like_count or 0),
                            int(account.view_count or 0),
                            int(account.post_count or 0),
                        )
                        unchanged = before == after
                        report_by_index[idx] = {
                            "platform": account.platform,
                            "username": account.username,
                            "profile_name": _profile_name(account),
                            "status": (
                                "успешно (данные без изменений)" if unchanged else "успешно"
                            ),
                            "follower_before": before[0],
                            "follower_after": after[0],
                            "like_before": before[1],
                            "like_after": after[1],
                            "view_before": before[2],
                            "view_after": after[2],
                            "post_before": before[3],
                            "post_after": after[3],
                            "elapsed_sec": round(max(0.0, time.perf_counter() - row_started), 3),
                            "detail": "",
                        }
                        _mark_progress(success=True, failed=False)
                        _persist_run_item(account.id, status="done", worker=None, detail="")
                    except Exception as e:
                        _mark_profile_unavailable_if_applicable(account, e)
                        detail = str(e).replace("\r\n", " ").replace("\n", " ").strip()
                        if len(detail) > 800:
                            detail = detail[:797] + "..."
                        account.refresh_from_db()
                        if before is not None:
                            fb, lb, vb, pb = before
                        else:
                            fb = int(account.follower_count or 0)
                            lb = int(account.like_count or 0)
                            vb = int(account.view_count or 0)
                            pb = int(account.post_count or 0)
                        report_by_index[idx] = {
                            "platform": account.platform,
                            "username": account.username,
                            "profile_name": _profile_name(account),
                            "status": "ошибка",
                            "follower_before": fb,
                            "follower_after": fb,
                            "like_before": lb,
                            "like_after": lb,
                            "view_before": vb,
                            "view_after": vb,
                            "post_before": pb,
                            "post_after": pb,
                            "elapsed_sec": round(max(0.0, time.perf_counter() - row_started), 3),
                            "detail": detail,
                        }
                        _mark_progress(success=False, failed=True, last_error=str(e))
                        _persist_run_item(account.id, status="error", worker=None, detail=detail)
                        print(f"[scheduled_refresh] {account.platform}/@{account.username}: {e}")
                    finally:
                        if attempted_network:
                            pause_sec = _refresh_all_delay_seconds(account)
                            if pause_sec > 0:
                                with cooldown_lock:
                                    platform_next_allowed_at[account.platform] = (
                                        max(
                                            platform_next_allowed_at.get(account.platform, 0.0),
                                            time.monotonic() + pause_sec,
                                        )
                                    )

        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            futures = [executor.submit(_worker) for _ in range(worker_count)]
            for f in futures:
                f.result()

        _finalize_run_detail_stale()

        for i, row in enumerate(report_by_index):
            if row is not None:
                report_rows.append(row)
            else:
                acc_nf = accounts[i]
                acc_nf.refresh_from_db()
                fb = int(acc_nf.follower_count or 0)
                lb = int(acc_nf.like_count or 0)
                vb = int(acc_nf.view_count or 0)
                pb = int(acc_nf.post_count or 0)
                report_rows.append(
                    {
                        "platform": acc_nf.platform,
                        "username": acc_nf.username,
                        "profile_name": _profile_name(acc_nf),
                        "status": "не выполнено",
                        "follower_before": fb,
                        "follower_after": fb,
                        "like_before": lb,
                        "like_after": lb,
                        "view_before": vb,
                        "view_after": vb,
                        "post_before": pb,
                        "post_after": pb,
                        "elapsed_sec": "",
                        "detail": "остановка до обработки этого аккаунта",
                    },
                )
    finally:
        finished = timezone.now()
        state.is_running = False
        state.cancel_requested = False
        state.current_account = ""
        state.finished_at = finished
        # Сначала снимаем is_running — иначе при падении build_auto_refresh_report_csv
        # state.save ниже не выполнится, и UI навсегда остаётся на «Уже запущено» при 100%.
        try:
            state.save(
                update_fields=[
                    "is_running",
                    "cancel_requested",
                    "current_account",
                    "finished_at",
                    "updated_at",
                ],
            )
        except Exception as e:
            print(f"[scheduled_refresh] failed to persist run finished (is_running): {e}")
        if cfg.auto_refresh_csv_report:
            try:
                note = (state.last_error or "").strip()
                batch_post_total = sum(int(getattr(a, "post_count", 0) or 0) for a in accounts)
                qs_dash = _apply_visibility_filters(Account.objects.all(), False, False)
                dash_agg = qs_dash.aggregate(Sum("post_count"))
                dashboard_post_total = int(dash_agg.get("post_count__sum") or 0)
                dashboard_account_count = int(qs_dash.count())
                state.last_report_csv = build_auto_refresh_report_csv(
                    rows=report_rows,
                    started_at=state.started_at,
                    finished_at=finished,
                    source=state.source or source,
                    total_accounts=len(accounts),
                    run_note=note,
                    batch_post_total=batch_post_total,
                    dashboard_post_total=dashboard_post_total,
                    dashboard_account_count=dashboard_account_count,
                )
                state.last_report_generated_at = finished
                state.save(
                    update_fields=["last_report_csv", "last_report_generated_at", "updated_at"],
                )
            except Exception as e:
                print(f"[scheduled_refresh] CSV report build/save failed: {e}")
        try:
            def _to_int(v):
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

            current_total_views = int(Account.objects.aggregate(total=Sum("view_count")).get("total") or 0)
            local_dt = timezone.localtime(finished)
            local_date = local_dt.date()
            prev_point = AutoRefreshPoint.objects.filter(
                measured_at__lt=finished,
            ).order_by("-measured_at").first()
            first_today = AutoRefreshPoint.objects.filter(
                local_date=local_date,
            ).order_by("measured_at").first()
            prev_total = int(prev_point.view_count_total) if prev_point else current_total_views
            day_start_total = int(first_today.view_count_total) if first_today else current_total_views
            slot_label = local_dt.strftime("%H:%M")
            platform_deltas: dict[str, int] = {}
            for row in report_rows:
                platform = str(row.get("platform") or "").strip().lower()
                if not platform:
                    continue
                before_v = _to_int(row.get("view_before"))
                after_v = _to_int(row.get("view_after"))
                if before_v is None or after_v is None:
                    continue
                platform_deltas[platform] = int(platform_deltas.get(platform, 0) + (after_v - before_v))
            AutoRefreshPoint.objects.create(
                local_date=local_date,
                source=source or "scheduler",
                slot_label=slot_label,
                view_count_total=current_total_views,
                view_delta_from_prev_point=current_total_views - prev_total,
                view_delta_from_day_start=current_total_views - day_start_total,
                platform_deltas=platform_deltas,
            )
        except Exception as e:
            print(f"[scheduled_refresh] failed to persist AutoRefreshPoint: {e}")
        _auto_refresh_lock.release()
        queued_run = None
        with _queued_refresh_lock:
            if _queued_refresh_requested:
                queued_run = (str(_queued_refresh_source or "scheduler"), bool(_queued_refresh_fast_start))
                _queued_refresh_requested = False
                _queued_refresh_source = "scheduler"
                _queued_refresh_fast_start = False
        if queued_run:
            next_source, next_fast_start = queued_run
            try:
                threading.Thread(
                    target=_scheduled_refresh,
                    kwargs={"source": next_source, "fast_start": next_fast_start},
                    daemon=True,
                ).start()
            except Exception as e:
                print(f"[scheduled_refresh] failed to start queued run: {e}")


def _scheduled_audience_refresh() -> None:
    """Съём аудитории TikTok/Instagram в фоне (не блокирует планировщик)."""

    def _run() -> None:
        from django.db import close_old_connections
        from django.utils import timezone

        from .audience import refresh_audience_for_account
        from .models import Account, GlobalVisibilityConfig, Platform, RefreshScheduleConfig

        close_old_connections()
        try:
            cfg = RefreshScheduleConfig.get()
            hidden_platforms: set[str] = set()
            if not bool(getattr(cfg, "include_hidden_platform_accounts", False)):
                try:
                    hidden_platforms = {
                        str(v).strip().lower()
                        for v in (GlobalVisibilityConfig.get().hidden_platforms or [])
                        if str(v).strip()
                    }
                except Exception:
                    hidden_platforms = set()
            qs = Account.objects.filter(
                platform__in=(Platform.TIKTOK, Platform.INSTAGRAM),
                profile_unavailable=False,
            ).select_related("profile")
            if hidden_platforms:
                qs = qs.exclude(platform__in=hidden_platforms)
            if not bool(getattr(cfg, "include_hidden_profile_accounts", False)):
                qs = qs.exclude(profile__is_hidden=True)
            cutoff = timezone.now() - timedelta(hours=20)
            for acc in qs.iterator(chunk_size=20):
                try:
                    if acc.audience_last_synced_at and acc.audience_last_synced_at >= cutoff:
                        continue
                    refresh_audience_for_account(acc)
                except Exception as e:
                    print(f"[audience_scheduled] account {acc.id} {acc.platform}/@{acc.username}: {e}")
                time.sleep(10)
        finally:
            close_old_connections()

    try:
        threading.Thread(target=_run, daemon=True, name="scheduled-audience").start()
    except Exception as e:
        print(f"[audience_scheduled] failed to start thread: {e}")
