"""Сбросить зависший is_running автообновления / refresh_all (после warm_tiktok, сбоя воркеров)."""
from django.core.management.base import BaseCommand

from accounts.refresh_state import clear_stale_refresh_runs_if_needed, clear_stuck_refresh_run


class Command(BaseCommand):
    help = "Снять is_running с AutoRefreshState и RefreshAllState, если прогон завис."

    def add_arguments(self, parser):
        parser.add_argument(
            "--force",
            action="store_true",
            help="Сбросить даже если таймаут «зависания» ещё не наступил.",
        )

    def handle(self, *args, **options):
        if options["force"]:
            cleared = clear_stuck_refresh_run(
                reason="Сброшено вручную (manage.py clear_refresh_run_state --force).",
            )
        else:
            cleared = clear_stale_refresh_runs_if_needed()
        if not cleared:
            self.stdout.write(self.style.SUCCESS("Нет зависших прогонов (is_running=false)."))
            return
        self.stdout.write(self.style.SUCCESS(f"Сброшено: {', '.join(cleared)}"))
