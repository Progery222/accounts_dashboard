import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from django.apps import AppConfig
from django.db.models import Sum

_scheduler = None
_auto_refresh_lock = threading.Lock()


def get_scheduler():
    return _scheduler


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
            IntervalTrigger(hours=config.interval_hours),
            id="auto_refresh_interval",
            replace_existing=True,
        )
    elif config.mode == "times":
        for i, t in enumerate(config.times):
            try:
                h, m = map(int, t.split(":"))
                sched.add_job(
                    _scheduled_refresh,
                    CronTrigger(hour=h, minute=m),
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
            from .models import AutoRefreshState

            _scheduler = BackgroundScheduler(timezone="Europe/Moscow")
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

            # Fixed nightly refresh at 03:00 Moscow — always present
            _scheduler.add_job(
                _scheduled_refresh,
                CronTrigger(hour=3, minute=0),
                id="daily_refresh_03",
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
    from django.utils import timezone
    from .auto_refresh_csv import build_auto_refresh_report_csv
    from .models import (
        Account,
        AutoRefreshPoint,
        AutoRefreshState,
        RefreshScheduleConfig,
        GlobalVisibilityConfig,
    )
    from .views import (
        _apply_refresh,
        _mark_profile_unavailable_if_applicable,
        _refresh_all_delay_seconds,
    )

    if not _auto_refresh_lock.acquire(blocking=False):
        return

    cfg = RefreshScheduleConfig.get()
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
    state.save(update_fields=[
        "is_running", "source", "cancel_requested", "total_accounts", "processed_accounts",
        "success_accounts", "failed_accounts", "current_account",
        "last_error", "started_at", "finished_at", "updated_at",
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

                    with state_lock:
                        state.current_account = f"{account.platform}/@{account.username}"
                        state.save(update_fields=["current_account", "updated_at"])

                    try:
                        if stop_requested.is_set():
                            return
                        if cutoff is not None and account.updated_at and account.updated_at >= cutoff:
                            report_by_index[idx] = {
                                **_empty_metrics_row(
                                    account,
                                    "пропущен",
                                    f"недавно обновлён (≤ {skip_recent_hours} ч)",
                                ),
                                "elapsed_sec": round(max(0.0, time.perf_counter() - row_started), 3),
                            }
                            _mark_progress(success=True, failed=False)
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
                    except Exception as e:
                        _mark_profile_unavailable_if_applicable(account, e)
                        detail = str(e).replace("\r\n", " ").replace("\n", " ").strip()
                        if len(detail) > 800:
                            detail = detail[:797] + "..."
                        report_by_index[idx] = {
                            **_empty_metrics_row(account, "ошибка", detail),
                            "elapsed_sec": round(max(0.0, time.perf_counter() - row_started), 3),
                        }
                        _mark_progress(success=False, failed=True, last_error=str(e))
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

        for i, row in enumerate(report_by_index):
            if row is not None:
                report_rows.append(row)
            else:
                report_rows.append(
                    _empty_metrics_row(
                        accounts[i],
                        "не выполнено",
                        "остановка до обработки этого аккаунта",
                    ),
                )
    finally:
        finished = timezone.now()
        state.is_running = False
        state.cancel_requested = False
        state.current_account = ""
        state.finished_at = finished
        save_fields = [
            "is_running", "cancel_requested", "current_account", "finished_at", "updated_at",
        ]
        if cfg.auto_refresh_csv_report:
            note = (state.last_error or "").strip()
            state.last_report_csv = build_auto_refresh_report_csv(
                rows=report_rows,
                started_at=state.started_at,
                finished_at=finished,
                source=state.source or source,
                total_accounts=len(accounts),
                run_note=note,
            )
            state.last_report_generated_at = finished
            save_fields.extend(["last_report_csv", "last_report_generated_at"])
        state.save(update_fields=save_fields)
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
