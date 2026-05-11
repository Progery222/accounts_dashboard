"""
Запустить APScheduler как отдельный процесс (вне gunicorn).

Используется на проде, чтобы scheduler не дублировался по N gunicorn-воркерам:
  - веб-контейнер: RUN_SCHEDULER=false (gunicorn config.wsgi)
  - scheduler-контейнер: python manage.py run_scheduler
    (RUN_SCHEDULER можно не задавать или явно RUN_SCHEDULER=true).

В веб-процессе планировщик не поднимается, поэтому POST /api/accounts/schedule/
обновляет только БД. Этот цикл периодически подтягивает конфиг из БД в память
планировщика (см. apply_schedule_config).
"""
import os
import signal
import time

from django.core.management.base import BaseCommand

# Интервал синхронизации расписания из БД (секунды).
_SCHEDULE_SYNC_SEC = 30.0


class Command(BaseCommand):
    help = "Run APScheduler in foreground (separate process from gunicorn)."

    def handle(self, *args, **options):
        os.environ.setdefault("RUN_SCHEDULER", "true")

        from accounts.apps import apply_schedule_config, get_scheduler, schedule_jobs_signature
        from accounts.models import RefreshScheduleConfig

        sched = get_scheduler()
        if sched is None:
            self.stderr.write(
                "Scheduler не запустился в AccountsConfig.ready(). "
                "Проверьте RUN_SCHEDULER и логи."
            )
            return

        self.stdout.write(self.style.SUCCESS("Scheduler started; jobs:"))
        for job in sched.get_jobs():
            self.stdout.write(f"  - {job.id}: next={job.next_run_time}")

        stop = {"flag": False}
        last_sig = schedule_jobs_signature(RefreshScheduleConfig.get())

        def _on_signal(signum, _frame):
            self.stdout.write(f"Received signal {signum}, shutting down…")
            stop["flag"] = True

        signal.signal(signal.SIGINT, _on_signal)
        signal.signal(signal.SIGTERM, _on_signal)

        try:
            acc = 0.0
            while not stop["flag"]:
                time.sleep(1.0)
                if stop["flag"]:
                    break
                acc += 1.0
                if acc < _SCHEDULE_SYNC_SEC:
                    continue
                acc = 0.0
                try:
                    cfg = RefreshScheduleConfig.get()
                    sig = schedule_jobs_signature(cfg)
                    if sig != last_sig:
                        last_sig = sig
                        apply_schedule_config(cfg, sched)
                        self.stdout.write(
                            f"[run_scheduler] расписание из БД применено: enabled={sig[0]} mode={sig[1]!r}"
                        )
                        for job in sched.get_jobs():
                            jid = str(job.id)
                            if jid.startswith("auto_refresh_") or jid == "daily_refresh_03":
                                self.stdout.write(f"  - {jid}: next={job.next_run_time}")
                except Exception as exc:
                    self.stderr.write(f"[run_scheduler] sync schedule from DB failed: {exc}")
        finally:
            try:
                sched.shutdown(wait=False)
            except Exception:
                pass
            self.stdout.write("Scheduler stopped.")
