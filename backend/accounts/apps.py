import logging
import os
import sys
import threading
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from datetime import timedelta
from zoneinfo import ZoneInfo

from django.apps import AppConfig
from django.db import transaction
from django.db.models import Sum

# Единая таймзона для Cron/Interval (иначе на UTC-хосте «03:00» nightly = 06:00 МСК).
SCHEDULER_TZ = ZoneInfo("Europe/Moscow")

_scheduler = None
_last_schedule_sig: tuple | None = None
_schedule_sync_lock = threading.Lock()
SCHEDULE_SYNC_JOB_ID = "schedule_sync_from_db"
_auto_refresh_lock = threading.Lock()
_queued_refresh_lock = threading.Lock()


def _release_auto_refresh_lock() -> None:
    try:
        _auto_refresh_lock.release()
    except RuntimeError:
        pass
_queued_refresh_requested = False
_queued_refresh_source = "scheduler"
_queued_refresh_fast_start = False
_queued_refresh_runs: list[tuple[str, bool]] = []

logger = logging.getLogger(__name__)


def _scheduler_job_defaults() -> dict:
    return {"max_instances": 1, "coalesce": True, "misfire_grace_time": 7200}


def _auto_refresh_float_env(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or not str(raw).strip():
        return default
    try:
        return float(str(raw).strip())
    except (TypeError, ValueError):
        return default


def _auto_refresh_max_queued() -> int:
    return max(1, min(8, int(_auto_refresh_float_env("AUTO_REFRESH_MAX_QUEUED", 3))))


def peek_pending_scheduled_refresh_count() -> int:
    with _queued_refresh_lock:
        if _queued_refresh_runs:
            return len(_queued_refresh_runs)
        return 1 if _queued_refresh_requested else 0


def _enqueue_scheduled_refresh(*, source: str, fast_start: bool) -> None:
    global _queued_refresh_runs
    cap = _auto_refresh_max_queued()
    with _queued_refresh_lock:
        if len(_queued_refresh_runs) >= cap:
            dropped = _queued_refresh_runs.pop(0)
            print(
                f"[scheduled_refresh] queue full ({cap}): dropped oldest "
                f"source={dropped[0]!r}",
                file=sys.stderr,
            )
        _queued_refresh_runs.append((source or "scheduler", bool(fast_start)))


def _pop_next_queued_run() -> tuple[str, bool] | None:
    with _queued_refresh_lock:
        if not _queued_refresh_runs:
            return None
        return _queued_refresh_runs.pop(0)


def get_scheduler():
    return _scheduler


def sync_schedule_from_db(*, force: bool = False) -> None:
    """Подтянуть расписание из БД (после POST /api/accounts/schedule/)."""
    global _last_schedule_sig
    sched = _scheduler
    if sched is None:
        return
    with _schedule_sync_lock:
        try:
            from .models import RefreshScheduleConfig

            cfg = RefreshScheduleConfig.get()
            sig = schedule_jobs_signature(cfg)
            if not force and sig == _last_schedule_sig:
                return
            _last_schedule_sig = sig
            apply_schedule_config(cfg, sched)
            print(
                f"[scheduler] расписание из БД: enabled={cfg.enabled} mode={cfg.mode!r} "
                f"times={cfg.times!r}",
                file=sys.stderr,
            )
        except Exception as e:
            print(f"[scheduler] sync schedule from DB failed: {e}", file=sys.stderr)


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

    # Снять пользовательские слоты и устаревшие фиксированные nightly (03:00 / audience 04:15).
    _legacy_job_ids = frozenset({"daily_refresh_03", "daily_audience_0415"})
    for job in list(sched.get_jobs()):
        jid = str(job.id)
        if jid.startswith("auto_refresh_") or jid in _legacy_job_ids:
            try:
                sched.remove_job(jid)
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
_COMPANION_API_PORT = 8010


def _runserver_bind_port() -> int | None:
    if "runserver" not in sys.argv:
        return None
    for arg in sys.argv[1:]:
        a = str(arg).strip()
        if ":" in a:
            try:
                return int(a.rsplit(":", 1)[-1])
            except ValueError:
                continue
        if a.isdigit():
            return int(a)
    return 8000


def _apply_runserver_scheduler_default() -> None:
    if "runserver" not in sys.argv:
        return
    for arg in sys.argv[1:]:
        a = str(arg).strip()
        if ":8010" in a or a.endswith(":8010") or a == "8010":
            os.environ["RUN_SCHEDULER"] = "false"
            print(
                "[scheduler] auto-disabled: runserver на :8010 "
                "(основной API и cron — :8000)",
                file=sys.stderr,
            )
            return


def _scheduler_enabled_from_env() -> bool:
    """
    Включать ли scheduler в этом процессе.

    На проде под gunicorn с N воркерами scheduler стартует в каждом воркере,
    что приводит к дублям задач. Управляем явным env:

      • RUN_SCHEDULER=true  — стартовать (например, в отдельном процессе
        gunicorn --workers 1 или management-команде).
      • RUN_SCHEDULER=false — не стартовать (для остальных gunicorn-воркеров).

    Локально runserver 127.0.0.1:8010 без RUN_SCHEDULER → планировщик выключен.

    Если переменная не задана — поведение как раньше: стартовать.
    """
    _apply_runserver_scheduler_default()
    raw = os.environ.get("RUN_SCHEDULER")
    if raw is None:
        return True
    s = raw.strip().lower()
    if s in _TRUE:
        return True
    if s in _FALSE:
        return False
    return True


def _skip_accounts_startup_on_runserver_parent() -> bool:
    """
    При runserver с autoreload ready() вызывается дважды: в родителе-наблюдателе
    (RUN_MAIN не задан) и в рабочем процессе (RUN_MAIN=true). Планировщик и reconcile
    нужны только в рабочем процессе.

    С ``runserver --noreload`` один процесс без RUN_MAIN — здесь НЕ пропускаем,
    иначе APScheduler никогда не стартует и слоты 06:00 / 10:11 не срабатывают.
    """
    if "runserver" not in sys.argv:
        return False
    if "--noreload" in sys.argv:
        return False
    return os.environ.get("RUN_MAIN") != "true"


class AccountsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "accounts"

    def ready(self):
        from . import signals  # noqa: F401

        if _skip_accounts_startup_on_runserver_parent():
            return
        # При management-командах (migrate, makemigrations, test, ...) scheduler
        # не нужен — может мешать миграциям и валить тесты.
        if any(a in sys.argv for a in (
            "migrate", "makemigrations", "collectstatic", "shell",
            "test", "createsuperuser", "loaddata", "dumpdata",
        )):
            try:
                from platforms.apify.poller import start_apify_poller

                start_apify_poller()
            except Exception as exc:
                print(f"[apify] poller start skipped: {exc}", file=sys.stderr)
            return
        try:
            from platforms.worker_pool import reconcile_orphan_worker_daemons

            reconcile_orphan_worker_daemons()
        except Exception as exc:
            print(f"[worker_pool] reconcile at startup failed: {exc}", file=sys.stderr)
        try:
            from platforms.apify.poller import start_apify_poller

            start_apify_poller()
        except Exception as exc:
            print(f"[apify] poller start failed: {exc}", file=sys.stderr)
        if not _scheduler_enabled_from_env():
            print("[scheduler] disabled via RUN_SCHEDULER env")
            return
        self._start_scheduler()

    def _start_scheduler(self):
        global _scheduler
        try:
            from apscheduler.schedulers.background import BackgroundScheduler
            from .models import AutoRefreshState, RefreshAllState

            _scheduler = BackgroundScheduler(timezone=SCHEDULER_TZ)
            # Сброс «зависшего» is_running только при реальном перезапуске runserver,
            # не при manage.py shell / диагностических скриптах с django.setup().
            from .refresh_state import should_clear_stale_refresh_on_startup

            if should_clear_stale_refresh_on_startup():
                try:
                    state = AutoRefreshState.get()
                    if state.is_running:
                        state.is_running = False
                        state.current_account = ""
                        state.last_error = "Автообновление было прервано перезапуском процесса."
                        state.save(
                            update_fields=["is_running", "current_account", "last_error", "updated_at"],
                        )
                except Exception:
                    pass
                try:
                    rr = RefreshAllState.get()
                    if rr.is_running:
                        rr.is_running = False
                        rr.current_account = ""
                        rr.last_error = "Сбор всех аккаунтов был прерван перезапуском процесса."
                        rr.save(
                            update_fields=["is_running", "current_account", "last_error", "updated_at"],
                        )
                except Exception:
                    pass

            job_kw = _scheduler_job_defaults()
            from apscheduler.triggers.cron import CronTrigger
            from apscheduler.triggers.interval import IntervalTrigger

            from .auto_refresh_pulse import record_interval_pulse_snapshot

            _scheduler.add_job(
                sync_schedule_from_db,
                IntervalTrigger(seconds=30, timezone=SCHEDULER_TZ),
                id=SCHEDULE_SYNC_JOB_ID,
                replace_existing=True,
                **job_kw,
            )
            for legacy_id in ("pulse_hourly_snapshot",):
                try:
                    _scheduler.remove_job(legacy_id)
                except Exception:
                    pass
            _scheduler.add_job(
                record_interval_pulse_snapshot,
                CronTrigger(minute="0,30", timezone=SCHEDULER_TZ),
                id="pulse_interval_snapshot",
                replace_existing=True,
                **job_kw,
            )

            # Apply user-configured schedule (DB must be migrated already)
            try:
                from .models import RefreshScheduleConfig
                apply_schedule_config(RefreshScheduleConfig.get(), _scheduler)
            except Exception as e:
                print(f"[scheduler] could not load user schedule: {e}")

            _scheduler.start()
            print("[scheduler] started", file=sys.stderr)
            threading.Timer(2.0, lambda: sync_schedule_from_db(force=True)).start()
        except Exception as e:
            print(f"[scheduler] failed to start: {e}")


def _scheduled_refresh(*, source: str = "scheduler", fast_start: bool = False):
    global _queued_refresh_requested, _queued_refresh_source, _queued_refresh_fast_start
    import uuid

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
    from .refresh_cancel import RefreshCancelledError
    from .views import (
        _account_refresh_baseline,
        _apply_visibility_filters,
        _mark_profile_unavailable_if_applicable,
        _prewarm_workers,
        _refresh_all_cooldown_seconds,
        _refresh_link_clicks_for_accounts,
        _refresh_with_retry,
        _restore_account_refresh_baseline,
        humanize_refresh_run_detail,
    )
    from .db_connections import (
        ensure_fresh_db_connections,
        release_db_for_long_task,
        run_with_db_reconnect,
    )

    if not _auto_refresh_lock.acquire(blocking=False):
        # If a slot fires while a run is active, queue exactly one follow-up run
        # so scheduled times are not silently lost.
        with _queued_refresh_lock:
            _queued_refresh_requested = True
            _queued_refresh_source = source or "scheduler"
            _queued_refresh_fast_start = bool(_queued_refresh_fast_start or fast_start)
        print(
            "[scheduled_refresh] в очереди: другой прогон ещё запускается",
            file=sys.stderr,
            flush=True,
        )
        return

    bind_port = _runserver_bind_port()
    if bind_port == _COMPANION_API_PORT:
        _release_auto_refresh_lock()
        print(
            "[scheduled_refresh] skip: этот процесс runserver на :8010 "
            "(автообновление только на :8000)",
            file=sys.stderr,
        )
        return
    try:
        from .refresh_state import clear_stale_refresh_runs_if_needed

        cleared = clear_stale_refresh_runs_if_needed()
        if cleared:
            print(
                f"[scheduled_refresh] сброшен зависший прогон: {', '.join(cleared)}",
                file=sys.stderr,
                flush=True,
            )
        if AutoRefreshState.get().is_running:
            _enqueue_scheduled_refresh(source=source, fast_start=fast_start)
            print(
                "[scheduled_refresh] в очереди: ещё идёт автообновление",
                file=sys.stderr,
                flush=True,
            )
            return
        if RefreshAllState.get().is_running:
            _enqueue_scheduled_refresh(source=source, fast_start=fast_start)
            print(
                "[scheduled_refresh] в очереди: идёт «Обновить всё»",
                file=sys.stderr,
                flush=True,
            )
            return
        # Резервируем прогон до снятия lock: иначе два «Запустить сейчас» оба видят
        # is_running=False, один сбрасывает флаг — воркеры второго сразу выходят.
        state = AutoRefreshState.get()
        rr = RefreshAllState.get()
        if not rr.is_running and rr.cancel_requested:
            rr.cancel_requested = False
            rr.save(update_fields=["cancel_requested", "updated_at"])
        try:
            from platforms.worker_pool import clear_playwright_refresh_force_stop

            clear_playwright_refresh_force_stop()
        except Exception:
            pass
        now_reserve = timezone.now()
        state.is_running = True
        state.cancel_requested = False
        state.source = source or "scheduler"
        state.current_account = ""
        state.last_error = ""
        state.started_at = now_reserve
        state.finished_at = None
        state.save(
            update_fields=[
                "is_running",
                "cancel_requested",
                "source",
                "current_account",
                "last_error",
                "started_at",
                "finished_at",
                "updated_at",
            ],
        )
    except Exception as exc:
        print(
            f"[scheduled_refresh] проверка состояния не удалась: {exc}",
            file=sys.stderr,
            flush=True,
        )
        try:
            st_fail = AutoRefreshState.get()
            if st_fail.is_running and not (st_fail.run_detail or {}).get("items"):
                st_fail.is_running = False
                st_fail.save(update_fields=["is_running", "updated_at"])
        except Exception:
            pass
        return
    finally:
        # Не держим lock во время link clicks / prewarm — иначе «Запустить сейчас»
        # молча встаёт в очередь, а браузеры не поднимаются.
        _release_auto_refresh_lock()

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
                "auto_refresh_telegram_enabled",
                "auto_refresh_telegram_chat_id",
                "auto_refresh_telegram_chat_ids",
                "auto_refresh_platforms",
                "auto_refresh_profile_ids",
                "auto_refresh_owner_ids",
            ],
        )
    except Exception:
        pass
    skip_recent_hours = max(0, int(getattr(cfg, "skip_recent_hours", 0) or 0))
    cutoff = timezone.now() - timedelta(hours=skip_recent_hours) if skip_recent_hours > 0 else None
    # «Запустить сейчас» использует те же фильтры skip_recent_hours, что и запуск по расписанию.
    from .auto_refresh_scope import apply_auto_refresh_scope

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
    accounts_qs = apply_auto_refresh_scope(accounts_qs, cfg)
    from .refresh_queue import order_accounts_for_refresh, queryset_order_by_staleness

    accounts = order_accounts_for_refresh(list(queryset_order_by_staleness(accounts_qs)))
    print(
        f"[scheduled_refresh] start source={source} accounts={len(accounts)} "
        f"fast_start={fast_start}",
        file=sys.stderr,
        flush=True,
    )
    if not accounts:
        print(
            "[scheduled_refresh] нет аккаунтов для обновления (проверьте фильтры расписания)",
            file=sys.stderr,
            flush=True,
        )
        try:
            st_empty = AutoRefreshState.get()
            if st_empty.is_running:
                st_empty.is_running = False
                st_empty.finished_at = timezone.now()
                st_empty.save(
                    update_fields=["is_running", "finished_at", "updated_at"],
                )
        except Exception:
            pass
        queued_run = None
        with _queued_refresh_lock:
            if _queued_refresh_requested:
                queued_run = (
                    str(_queued_refresh_source or "scheduler"),
                    bool(_queued_refresh_fast_start),
                )
                _queued_refresh_requested = False
                _queued_refresh_source = "scheduler"
                _queued_refresh_fast_start = False
        if queued_run:
            next_source, next_fast_start = queued_run
            threading.Thread(
                target=_scheduled_refresh,
                kwargs={"source": next_source, "fast_start": next_fast_start},
                daemon=True,
            ).start()
        return

    from .refresh_priority import account_refresh_priority_session

    from .auto_refresh_pulse import (
        create_auto_refresh_point_from_report_rows,
        refresh_pulse_batch,
    )

    with account_refresh_priority_session(), refresh_pulse_batch():
        report_rows: list[dict] = []
        run_flags = {"cancelled": False}
        state = AutoRefreshState.get()
        try:
            from platforms.worker_pool import clear_playwright_refresh_force_stop

            clear_playwright_refresh_force_stop()
        except Exception:
            pass
        state.is_running = True
        state.cancel_requested = False
        state.source = source
        state.total_accounts = len(accounts)
        state.processed_accounts = 0
        state.success_accounts = 0
        state.failed_accounts = 0
        state.current_account = ""
        state.last_error = ""
        state.started_at = timezone.now()
        state.finished_at = None
        from .scrape_backend import scheduled_auto_refresh_worker_count

        worker_count_early = scheduled_auto_refresh_worker_count(accounts)
        from .refresh_skip_recent import build_initial_run_detail_items

        run_items_early, skip_initial = build_initial_run_detail_items(
            accounts,
            skip_recent_hours=skip_recent_hours,
            cutoff=cutoff,
        )
        state.processed_accounts = skip_initial
        state.success_accounts = skip_initial
        state.run_detail = {
            "items": run_items_early,
            "worker_count": worker_count_early,
        }
        state.save(update_fields=[
            "is_running", "cancel_requested", "source", "total_accounts",
            "processed_accounts", "success_accounts", "failed_accounts",
            "current_account", "last_error", "started_at", "finished_at",
            "run_detail", "updated_at",
        ])

        defer_link_clicks = bool(fast_start) or source == "manual"

        def _run_link_clicks() -> None:
            try:
                ensure_fresh_db_connections()
                _refresh_link_clicks_for_accounts(accounts, log_prefix="scheduled_refresh")
            except Exception as e:
                print(
                    f"[scheduled_refresh] link clicks failed: {e}",
                    file=sys.stderr,
                    flush=True,
                )

        if defer_link_clicks:
            threading.Thread(
                target=_run_link_clicks,
                daemon=True,
                name="auto-refresh-link-clicks",
            ).start()
        else:
            _run_link_clicks()

        # Предзапуск демонов — только если явно включён ACCOUNTS_AUTOREFRESH_PREWARM_PLAYWRIGHT
        # (иначе по одному окну на платформу при первом реальном запросе, без «шторма» окон).
        from django.conf import settings as dj_settings

        ig_preload: dict[str, dict] = {}

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
                "telegram": 1,
                "x": 1,
                "reddit": 2,
                "youtube": 1,
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

        from .scrape_backend import (
            accounts_needing_playwright,
            facebook_playwright_warm_needed,
            refresh_account_via_apify_sync,
            should_use_apify_for_account,
        )
        from .models import ApifyRefreshJobTrigger

        apify_batch_id = uuid.uuid4()
        try:
            from platforms.apify.abort import abort_active_apify_jobs

            aborted = abort_active_apify_jobs()
            if aborted:
                print(
                    f"[scheduled_refresh] отменено активных Apify jobs: {aborted}",
                    file=sys.stderr,
                    flush=True,
                )
        except Exception as exc:
            print(f"[scheduled_refresh] abort Apify jobs failed: {exc}", file=sys.stderr)
        from platforms.apify.batch_guard import enter_sync_apify_batch, leave_sync_apify_batch

        enter_sync_apify_batch(apify_batch_id)
        has_facebook = facebook_playwright_warm_needed(accounts)
        from .scrape_backend import BatchScrapeContext

        batch_scrape = BatchScrapeContext.for_accounts(accounts)
        fb_batch_guard = None
        if has_facebook:
            from platforms.facebook.rate_limit import FacebookRefreshBatchGuard

            fb_fb = batch_scrape.facebook_fallback
            if fb_fb is None or not fb_fb.enabled:
                fb_batch_guard = FacebookRefreshBatchGuard()

        from .facebook_refresh_lane import (
            begin_facebook_batch,
            batch_has_facebook,
            end_facebook_batch,
            ensure_facebook_playwright_daemon_ready,
            platform_claim_filter,
            submit_refresh_workers,
            try_mark_facebook_account_started,
            filter_accounts_for_playwright_prewarm,
            allocate_worker_slot,
        )

        has_fb_accounts = batch_has_facebook(accounts)
        begin_facebook_batch()
        try:
            from .parallel_account_queue import ParallelAccountQueue
            from .refresh_all_warm import RefreshAllWarmTracker

            warm_tracker = RefreshAllWarmTracker(accounts, label="scheduled_refresh")

            state_lock = threading.Lock()
            stop_requested = threading.Event()
            report_by_index: list[dict | None] = [None] * len(accounts)
            platform_limits = _platform_limits()
            account_queue = ParallelAccountQueue(len(accounts), platform_limits)
            from .refresh_skip_recent import apply_upfront_skip_recent

            apply_upfront_skip_recent(
                accounts,
                cutoff=cutoff,
                skip_recent_hours=skip_recent_hours,
                account_queue=account_queue,
                report_by_index=report_by_index,
                profile_name=_profile_name,
            )
            worker_count = scheduled_auto_refresh_worker_count(accounts)

            thread_slot_map: dict[int, int] = {}
            thread_slot_lock = threading.Lock()

            _fb_daemon_prepared = threading.Event()

            def _worker_slot(*, facebook_lane: bool) -> int:
                return allocate_worker_slot(
                    facebook_lane=facebook_lane,
                    thread_slot_map=thread_slot_map,
                    thread_slot_lock=thread_slot_lock,
                )

            def _persist_run_item(account_id: int, **kwargs) -> None:
                from accounts.run_detail_items import merge_run_detail_item

                def _write() -> None:
                    with transaction.atomic():
                        st = AutoRefreshState.objects.select_for_update().get(pk=1)
                        rd = dict(st.run_detail or {})
                        items = [dict(x) for x in (rd.get("items") or [])]
                        aid = int(account_id)
                        for i, it in enumerate(items):
                            if int(it.get("account_id", -1)) != aid:
                                continue
                            items[i] = merge_run_detail_item(it, kwargs)
                            break
                        rd["items"] = items
                        st.run_detail = rd
                        st.save(update_fields=["run_detail", "updated_at"])

                try:
                    run_with_db_reconnect(_write)
                except Exception as e:
                    print(f"[scheduled_refresh] run_detail update failed for {account_id}: {e}")

            st_plan = AutoRefreshState.objects.get(pk=1)
            rd_plan = dict(st_plan.run_detail or {})
            rd_plan["worker_count"] = worker_count
            rd_plan["apify_batch_id"] = str(apify_batch_id)
            st_plan.run_detail = rd_plan
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

            def _mark_progress(*, success: bool, failed: bool, last_error: str = "") -> None:
                def _write() -> None:
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

                with state_lock:
                    try:
                        run_with_db_reconnect(_write)
                    except Exception as e:
                        print(f"[scheduled_refresh] progress save failed: {e}")

            def _reload_account(idx: int) -> Account:
                ensure_fresh_db_connections()
                return Account.objects.select_related("profile").get(pk=accounts[idx].pk)

            def _worker(facebook_lane: bool) -> None:
                if facebook_lane and not _fb_daemon_prepared.is_set():
                    try:
                        ensure_facebook_playwright_daemon_ready()
                    except Exception as exc:
                        print(
                            f"[scheduled_refresh] Facebook daemon: {exc}",
                            file=sys.stderr,
                            flush=True,
                        )
                    _fb_daemon_prepared.set()
                while True:
                    if stop_requested.is_set():
                        return
                    ensure_fresh_db_connections()
                    with state_lock:
                        def _read_cancel_flag() -> None:
                            state.refresh_from_db(fields=["cancel_requested", "is_running"])

                        run_with_db_reconnect(_read_cancel_flag)
                        if bool(state.cancel_requested) or not bool(state.is_running):
                            run_flags["cancelled"] = True
                            if state.cancel_requested:
                                state.last_error = "Автообновление остановлено пользователем."
                            else:
                                prev = (state.last_error or "").strip()
                                state.last_error = prev or (
                                    "Прогон остановлен: is_running сброшен без cancel_requested "
                                    "(не кнопка «Остановить» — stale-clear, перезапуск или гонка)."
                                )[:500]
                            print(
                                "[scheduled_refresh] worker exit: "
                                f"cancel={state.cancel_requested} running={state.is_running} "
                                f"last_error={(state.last_error or '')[:120]!r}",
                                file=sys.stderr,
                                flush=True,
                            )

                            def _save_stop_msg() -> None:
                                state.save(update_fields=["last_error", "updated_at"])

                            run_with_db_reconnect(_save_stop_msg)
                            stop_requested.set()
                            return

                    idx = account_queue.claim(
                        lambda i: accounts[i].platform,
                        stop_event=stop_requested,
                        platform_filter=platform_claim_filter(facebook_lane=facebook_lane),
                    )
                    if idx is None:
                        return

                    account = _reload_account(idx)
                    if (
                        facebook_lane
                        and str(account.platform) == "facebook"
                        and not try_mark_facebook_account_started(account.id)
                    ):
                        account_queue.abandon(idx, account.platform)
                        continue
                    from .warm_run_detail import is_refresh_cancel_requested

                    if is_refresh_cancel_requested():
                        stop_requested.set()
                        return
                    release_db_for_long_task()
                    warm_tracker.wait_warm_before_refresh(account.platform)
                    if is_refresh_cancel_requested():
                        stop_requested.set()
                        return
                    account = _reload_account(idx)
                    row_started = time.perf_counter()
                    attempted_network = False
                    refresh_failure_exc = None
                    refresh_baseline = None
                    try:
                        if stop_requested.is_set():
                            return

                        slot = _worker_slot(facebook_lane=facebook_lane)

                        def _mark_current_account() -> None:
                            state.current_account = f"{account.platform}/@{account.username}"
                            state.save(update_fields=["current_account", "updated_at"])

                        with state_lock:
                            run_with_db_reconnect(_mark_current_account)
                        _persist_run_item(
                            account.id,
                            status="running",
                            worker=slot,
                            detail=(
                                "Apify (синхронно)…"
                                if should_use_apify_for_account(account, batch_ctx=batch_scrape)
                                else "запуск браузера…"
                            ),
                        )

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
                            elif (
                                account.platform == "facebook"
                                and fb_batch_guard is not None
                                and not should_use_apify_for_account(account, batch_ctx=batch_scrape)
                                and fb_batch_guard.is_tripped()
                            ):
                                account.refresh_from_db()
                                fb = int(account.follower_count or 0)
                                lb = int(account.like_count or 0)
                                vb = int(account.view_count or 0)
                                pb = int(account.post_count or 0)
                                skip_detail = fb_batch_guard.skip_detail()
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
                                    "elapsed_sec": round(
                                        max(0.0, time.perf_counter() - row_started), 3
                                    ),
                                    "detail": skip_detail,
                                }
                                _mark_progress(success=True, failed=False)
                                _persist_run_item(
                                    account.id,
                                    status="skipped",
                                    worker=None,
                                    detail=skip_detail,
                                )
                            elif (
                                account.platform == "tiktok"
                                and batch_scrape.tiktok_captcha_tripped()
                                and not should_use_apify_for_account(account, batch_ctx=batch_scrape)
                            ):
                                account.refresh_from_db()
                                fb = int(account.follower_count or 0)
                                lb = int(account.like_count or 0)
                                vb = int(account.view_count or 0)
                                pb = int(account.post_count or 0)
                                err_detail = batch_scrape.tiktok_captcha_skip_detail()
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
                                    "elapsed_sec": round(
                                        max(0.0, time.perf_counter() - row_started), 3
                                    ),
                                    "detail": err_detail,
                                }
                                _mark_progress(success=False, failed=True, last_error=err_detail)
                                _persist_run_item(
                                    account.id,
                                    status="error",
                                    worker=None,
                                    detail=err_detail,
                                )
                            elif should_use_apify_for_account(account, batch_ctx=batch_scrape):
                                from accounts.models import ApifyRefreshJobStatus

                                account.refresh_from_db()
                                before = (
                                    int(account.follower_count or 0),
                                    int(account.like_count or 0),
                                    int(account.view_count or 0),
                                    int(account.post_count or 0),
                                )
                                attempted_network = True
                                _persist_run_item(
                                    account.id,
                                    status="running",
                                    worker=slot,
                                    detail="Apify (синхронно)…",
                                )
                                try:
                                    refresh_account_via_apify_sync(
                                        account,
                                        trigger=ApifyRefreshJobTrigger.SCHEDULER,
                                        parent_batch_id=apify_batch_id,
                                        batch_ctx=batch_scrape,
                                    )
                                except Exception as e:
                                    detail = humanize_refresh_run_detail(e)
                                    _mark_profile_unavailable_if_applicable(account, e)
                                    report_by_index[idx] = {
                                        "platform": account.platform,
                                        "username": account.username,
                                        "profile_name": _profile_name(account),
                                        "status": "ошибка",
                                        "follower_before": before[0],
                                        "follower_after": before[0],
                                        "like_before": before[1],
                                        "like_after": before[1],
                                        "view_before": before[2],
                                        "view_after": before[2],
                                        "post_before": before[3],
                                        "post_after": before[3],
                                        "elapsed_sec": round(
                                            max(0.0, time.perf_counter() - row_started), 3
                                        ),
                                        "detail": detail,
                                    }
                                    _mark_progress(success=False, failed=True, last_error=detail)
                                    _persist_run_item(
                                        account.id,
                                        status="error",
                                        worker=None,
                                        detail=detail[:800],
                                    )
                                else:
                                    from accounts.models import ApifyRefreshJob

                                    job = (
                                        ApifyRefreshJob.objects.filter(account_id=account.id)
                                        .order_by("-id")
                                        .first()
                                    )
                                    account = _reload_account(idx)
                                    after = (
                                        int(account.follower_count or 0),
                                        int(account.like_count or 0),
                                        int(account.view_count or 0),
                                        int(account.post_count or 0),
                                    )
                                    if job and job.status != ApifyRefreshJobStatus.SUCCEEDED:
                                        detail = (job.error_message or "Ошибка Apify")[:800]
                                        report_by_index[idx] = {
                                            "platform": account.platform,
                                            "username": account.username,
                                            "profile_name": _profile_name(account),
                                            "status": "ошибка",
                                            "follower_before": before[0],
                                            "follower_after": before[0],
                                            "like_before": before[1],
                                            "like_after": before[1],
                                            "view_before": before[2],
                                            "view_after": before[2],
                                            "post_before": before[3],
                                            "post_after": before[3],
                                            "elapsed_sec": round(
                                                max(0.0, time.perf_counter() - row_started), 3
                                            ),
                                            "detail": detail,
                                        }
                                        _mark_progress(success=False, failed=True, last_error=detail)
                                        _persist_run_item(
                                            account.id,
                                            status="error",
                                            worker=None,
                                            detail=detail[:800],
                                        )
                                    else:
                                        unchanged = before == after
                                        report_by_index[idx] = {
                                            "platform": account.platform,
                                            "username": account.username,
                                            "profile_name": _profile_name(account),
                                            "status": (
                                                "успешно (данные без изменений)"
                                                if unchanged
                                                else "успешно"
                                            ),
                                            "follower_before": before[0],
                                            "follower_after": after[0],
                                            "like_before": before[1],
                                            "like_after": after[1],
                                            "view_before": before[2],
                                            "view_after": after[2],
                                            "post_before": before[3],
                                            "post_after": after[3],
                                            "elapsed_sec": round(
                                                max(0.0, time.perf_counter() - row_started), 3
                                            ),
                                            "detail": "",
                                        }
                                        _mark_progress(success=True, failed=False)
                                        _persist_run_item(
                                            account.id,
                                            status="done",
                                            worker=None,
                                            detail="",
                                        )
                            else:
                                if is_refresh_cancel_requested():
                                    stop_requested.set()
                                    return
                                ensure_fresh_db_connections()
                                account = _reload_account(idx)
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
                                refresh_baseline = _account_refresh_baseline(account)
                                _persist_run_item(
                                    account.id,
                                    status="running",
                                    worker=slot,
                                    detail="съём данных…",
                                )
                                try:
                                    _refresh_with_retry(account, scraped=scraped)
                                except RefreshCancelledError:
                                    _restore_account_refresh_baseline(account.pk, refresh_baseline)
                                    raise
                                if is_refresh_cancel_requested():
                                    _restore_account_refresh_baseline(account.pk, refresh_baseline)
                                    raise RefreshCancelledError("Остановлено пользователем")
                                account = run_with_db_reconnect(
                                    lambda: Account.objects.get(pk=account.pk),
                                )
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
                        except RefreshCancelledError:
                            if attempted_network:
                                _restore_account_refresh_baseline(account.pk, refresh_baseline)
                            if before is not None:
                                fb, lb, vb, pb = before
                            else:
                                fb = lb = vb = pb = 0
                            report_by_index[idx] = {
                                "platform": account.platform,
                                "username": account.username,
                                "profile_name": _profile_name(account),
                                "status": "отменён",
                                "follower_before": fb,
                                "follower_after": fb,
                                "like_before": lb,
                                "like_after": lb,
                                "view_before": vb,
                                "view_after": vb,
                                "post_before": pb,
                                "post_after": pb,
                                "elapsed_sec": round(max(0.0, time.perf_counter() - row_started), 3),
                                "detail": "Остановлено пользователем",
                            }
                            _mark_progress(success=False, failed=False)
                            _persist_run_item(
                                account.id,
                                status="cancelled",
                                worker=None,
                                detail="Остановлено пользователем",
                            )
                            stop_requested.set()
                        except Exception as e:
                            from accounts.facebook_scrape_fallback import (
                                handle_facebook_playwright_batch_error,
                                retry_facebook_via_apify_after_playwright_failure,
                            )

                            refresh_failure_exc = e
                            handle_facebook_playwright_batch_error(
                                account,
                                e,
                                batch_ctx=batch_scrape,
                                fb_batch_guard=fb_batch_guard,
                            )
                            batch_scrape.on_tiktok_playwright_error(account, e)
                            apify_recovered = False
                            if account.platform == "tiktok":
                                from accounts.tiktok_scrape_fallback import (
                                    retry_tiktok_via_apify_after_captcha,
                                )

                                try:
                                    apify_acc = retry_tiktok_via_apify_after_captcha(
                                        account,
                                        e,
                                        batch_ctx=batch_scrape,
                                        trigger=ApifyRefreshJobTrigger.SCHEDULER,
                                        parent_batch_id=apify_batch_id,
                                    )
                                except Exception as apify_exc:
                                    e = apify_exc
                                    refresh_failure_exc = apify_exc
                                else:
                                    if apify_acc is not None:
                                        refresh_failure_exc = None
                                        account = apify_acc
                                        ensure_fresh_db_connections()
                                        account = _reload_account(idx)
                                        after = (
                                            int(account.follower_count or 0),
                                            int(account.like_count or 0),
                                            int(account.view_count or 0),
                                            int(account.post_count or 0),
                                        )
                                        if before is None:
                                            before = after
                                        unchanged = before == after
                                        report_by_index[idx] = {
                                            "platform": account.platform,
                                            "username": account.username,
                                            "profile_name": _profile_name(account),
                                            "status": (
                                                "успешно (данные без изменений)"
                                                if unchanged
                                                else "успешно"
                                            ),
                                            "follower_before": before[0],
                                            "follower_after": after[0],
                                            "like_before": before[1],
                                            "like_after": after[1],
                                            "view_before": before[2],
                                            "view_after": after[2],
                                            "post_before": before[3],
                                            "post_after": after[3],
                                            "elapsed_sec": round(
                                                max(0.0, time.perf_counter() - row_started), 3
                                            ),
                                            "detail": batch_scrape.tiktok_fallback.fallback_detail_suffix()
                                            if batch_scrape.tiktok_fallback is not None
                                            else "",
                                        }
                                        _mark_progress(success=True, failed=False)
                                        _persist_run_item(
                                            account.id,
                                            status="done",
                                            worker=None,
                                            detail=report_by_index[idx]["detail"],
                                        )
                                        apify_recovered = True
                            elif account.platform == "facebook":
                                try:
                                    apify_acc = retry_facebook_via_apify_after_playwright_failure(
                                        account,
                                        e,
                                        batch_ctx=batch_scrape,
                                        trigger=ApifyRefreshJobTrigger.SCHEDULER,
                                        parent_batch_id=apify_batch_id,
                                    )
                                except Exception as apify_exc:
                                    e = apify_exc
                                    refresh_failure_exc = apify_exc
                                else:
                                    if apify_acc is not None:
                                        refresh_failure_exc = None
                                        account = apify_acc
                                        ensure_fresh_db_connections()
                                        account = _reload_account(idx)
                                        after = (
                                            int(account.follower_count or 0),
                                            int(account.like_count or 0),
                                            int(account.view_count or 0),
                                            int(account.post_count or 0),
                                        )
                                        if before is None:
                                            before = after
                                        unchanged = before == after
                                        detail_fb = (
                                            batch_scrape.facebook_fallback.fallback_detail_suffix()
                                            if batch_scrape.facebook_fallback is not None
                                            else ""
                                        )
                                        report_by_index[idx] = {
                                            "platform": account.platform,
                                            "username": account.username,
                                            "profile_name": _profile_name(account),
                                            "status": (
                                                "успешно (данные без изменений)"
                                                if unchanged
                                                else "успешно"
                                            ),
                                            "follower_before": before[0],
                                            "follower_after": after[0],
                                            "like_before": before[1],
                                            "like_after": after[1],
                                            "view_before": before[2],
                                            "view_after": after[2],
                                            "post_before": before[3],
                                            "post_after": after[3],
                                            "elapsed_sec": round(
                                                max(0.0, time.perf_counter() - row_started), 3
                                            ),
                                            "detail": detail_fb,
                                        }
                                        _mark_progress(success=True, failed=False)
                                        _persist_run_item(
                                            account.id,
                                            status="done",
                                            worker=None,
                                            detail=detail_fb,
                                        )
                                        apify_recovered = True
                            if not apify_recovered:
                                _mark_profile_unavailable_if_applicable(account, e)
                                detail = humanize_refresh_run_detail(e)
                                logger.warning(
                                    "scheduled_refresh.account_failed",
                                    extra={
                                        "platform": account.platform,
                                        "username": account.username,
                                        "error": str(e)[:500],
                                    },
                                    exc_info=True,
                                )
                                ensure_fresh_db_connections()
                                account = _reload_account(idx)
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
                                    "elapsed_sec": round(
                                        max(0.0, time.perf_counter() - row_started), 3
                                    ),
                                    "detail": detail,
                                }
                                _mark_progress(success=False, failed=True, last_error=str(e))
                                _persist_run_item(
                                    account.id, status="error", worker=None, detail=detail
                                )
                                print(
                                    f"[scheduled_refresh] {account.platform}/@{account.username}: {e}"
                                )
                        finally:
                            if attempted_network and not is_refresh_cancel_requested():
                                delay_sec = (
                                    0.0
                                    if should_use_apify_for_account(account, batch_ctx=batch_scrape)
                                    else _refresh_all_cooldown_seconds(
                                        account,
                                        refresh_failure_exc,
                                    )
                                )
                                if delay_sec > 0:
                                    account_queue.set_platform_cooldown(
                                        account.platform,
                                        delay_sec,
                                    )
                                warm_tracker.after_network_refresh(account.platform)
                    finally:
                        if report_by_index[idx] is None:
                            account_queue.abandon(idx, account.platform)
                        else:
                            account_queue.finish(idx, account.platform)

            from .warm_run_detail import is_refresh_cancel_requested as _refresh_cancel_poll

            pw_accounts = filter_accounts_for_playwright_prewarm(
                accounts_needing_playwright(accounts),
            )
            try:
                from platforms.rumble.scraper import release_batch_resources, skip_playwright_prewarm

                if skip_playwright_prewarm():
                    release_batch_resources()
            except Exception:
                pass
            if pw_accounts and bool(getattr(dj_settings, "ACCOUNTS_AUTOREFRESH_PREWARM_PLAYWRIGHT", False)):
                print(
                    "[scheduled_refresh] подъём окон Playwright (по платформам)…",
                    file=sys.stderr,
                    flush=True,
                )
                try:
                    _prewarm_workers(pw_accounts, wait_browser_ready=True)
                    print("[scheduled_refresh] окна Playwright готовы", file=sys.stderr, flush=True)
                except Exception as e:
                    print(
                        f"[scheduled_refresh] подъём Playwright не удался: {e}",
                        file=sys.stderr,
                        flush=True,
                    )

            executor = ThreadPoolExecutor(max_workers=worker_count)
            futures = submit_refresh_workers(
                executor,
                _worker,
                worker_count=worker_count,
                has_facebook=has_fb_accounts,
            )
            pending = set(futures)
            try:
                while pending:
                    if _refresh_cancel_poll():
                        stop_requested.set()
                        from .refresh_interrupt import interrupt_refresh_playwright_workers

                        interrupt_refresh_playwright_workers(label="scheduled_refresh_cancel")
                        break
                    done, pending = wait(
                        pending,
                        timeout=1.5,
                        return_when=FIRST_COMPLETED,
                    )
                    for f in done:
                        try:
                            f.result()
                        except Exception:
                            pass
            finally:
                if stop_requested.is_set() or _refresh_cancel_poll():
                    run_flags["cancelled"] = True
                    executor.shutdown(wait=False, cancel_futures=True)
                    _finalize_run_detail_stale()
                else:
                    executor.shutdown(wait=True)

            from .warm_run_detail import is_refresh_cancel_requested as _refresh_cancelled

            warm_join_timeout = 15.0 if _refresh_cancelled() else None
            warm_tracker.join_warm_threads(timeout=warm_join_timeout)
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
            try:
                from platforms.rumble.scraper import release_batch_resources

                release_batch_resources()
            except Exception:
                pass
            end_facebook_batch()
            leave_sync_apify_batch()
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
            csv_body = ""
            try:
                note = (state.last_error or "").strip()
                batch_post_total = sum(int(getattr(a, "post_count", 0) or 0) for a in accounts)
                qs_dash = _apply_visibility_filters(
                    Account.objects.all(),
                    include_hidden_platforms=False,
                    include_hidden_profiles=False,
                )
                dash_agg = qs_dash.aggregate(Sum("post_count"))
                dashboard_post_total = int(dash_agg.get("post_count__sum") or 0)
                dashboard_account_count = int(qs_dash.count())
                csv_body = build_auto_refresh_report_csv(
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
                state.last_report_csv = csv_body
                state.last_report_generated_at = finished
                state.save(
                    update_fields=["last_report_csv", "last_report_generated_at", "updated_at"],
                )
            except Exception as e:
                print(f"[scheduled_refresh] CSV report build/save failed: {e}", file=sys.stderr)

            if cfg.auto_refresh_telegram_enabled and csv_body:
                from .telegram_report import (
                    auto_refresh_report_filename,
                    build_auto_refresh_telegram_text,
                    send_auto_refresh_telegram_report,
                    should_send_auto_refresh_telegram,
                )

                if should_send_auto_refresh_telegram(
                    run_was_cancelled=bool(run_flags.get("cancelled")),
                    last_error=(state.last_error or "").strip(),
                    report_rows=report_rows,
                    started_at=state.started_at,
                    finished_at=finished,
                    run_detail=state.run_detail,
                ):
                    try:
                        text = build_auto_refresh_telegram_text(
                            rows=report_rows,
                            started_at=state.started_at,
                            finished_at=finished,
                            total_accounts=len(accounts),
                        )
                        send_auto_refresh_telegram_report(
                            config=cfg,
                            text=text,
                            csv_body=csv_body,
                            filename=auto_refresh_report_filename(finished_at=finished),
                        )
                        state.last_telegram_error = ""
                        state.last_telegram_sent_at = finished
                        state.save(
                            update_fields=[
                                "last_telegram_error",
                                "last_telegram_sent_at",
                                "updated_at",
                            ],
                        )
                    except Exception as e:
                        err_msg = f"Не удалось отправить отчёт в Telegram: {e}"
                        logger.exception("scheduled_refresh.telegram_failed")
                        print(f"[scheduled_refresh] {err_msg}", file=sys.stderr)
                        state.last_telegram_error = err_msg[:2000]
                        state.save(update_fields=["last_telegram_error", "updated_at"])
            try:
                create_auto_refresh_point_from_report_rows(
                    report_rows,
                    source=state.source or source or "scheduler",
                    finished=finished,
                )
            except Exception as e:
                print(f"[scheduled_refresh] failed to persist AutoRefreshPoint: {e}")
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
        from .refresh_priority import account_refresh_priority_active

        if account_refresh_priority_active():
            print(
                "[audience_scheduled] пропуск: идёт обновление аналитики аккаунтов",
                file=sys.stderr,
            )
            return
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
