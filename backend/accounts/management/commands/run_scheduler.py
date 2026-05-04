"""
Запустить APScheduler как отдельный процесс (вне gunicorn).

Используется на проде, чтобы scheduler не дублировался по N gunicorn-воркерам:
  - веб-контейнер: RUN_SCHEDULER=false (gunicorn config.wsgi)
  - scheduler-контейнер: python manage.py run_scheduler
    (RUN_SCHEDULER можно не задавать или явно RUN_SCHEDULER=true).
"""
import os
import signal
import time

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Run APScheduler in foreground (separate process from gunicorn)."

    def handle(self, *args, **options):
        os.environ.setdefault("RUN_SCHEDULER", "true")

        from accounts.apps import get_scheduler

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

        def _on_signal(signum, _frame):
            self.stdout.write(f"Received signal {signum}, shutting down…")
            stop["flag"] = True

        signal.signal(signal.SIGINT, _on_signal)
        signal.signal(signal.SIGTERM, _on_signal)

        try:
            while not stop["flag"]:
                time.sleep(1.0)
        finally:
            try:
                sched.shutdown(wait=False)
            except Exception:
                pass
            self.stdout.write("Scheduler stopped.")
