import os
import sys
from django.apps import AppConfig

_scheduler = None


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

            _scheduler = BackgroundScheduler(timezone="Europe/Moscow")

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


def _scheduled_refresh():
    from .models import Account
    from .views import _apply_refresh, _mark_profile_unavailable_if_applicable

    for account in Account.objects.all():
        try:
            _apply_refresh(account)
        except Exception as e:
            _mark_profile_unavailable_if_applicable(account, e)
            print(f"[scheduled_refresh] {account.platform}/@{account.username}: {e}")
