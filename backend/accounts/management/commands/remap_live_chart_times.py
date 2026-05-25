"""Сдвинуть measured_at точек Live-графика в последние 24 ч (после импорта со старыми метками)."""

from django.core.management.base import BaseCommand
from django.utils import timezone

from accounts.models import AutoRefreshPoint
from accounts.snapshot_io import _normalize_imported_chart_times


class Command(BaseCommand):
    help = "Пересчитать measured_at AutoRefreshPoint в окно последних 24 часов."

    def add_arguments(self, parser):
        parser.add_argument(
            "--force",
            action="store_true",
            help="Всегда раскладывать все точки по 24 ч (даже если разброс нормальный).",
        )

    def handle(self, *args, **options):
        force = bool(options.get("force"))
        pts = list(AutoRefreshPoint.objects.order_by("measured_at"))
        if not pts:
            self.stdout.write("Точек нет — нечего пересчитывать.")
            return
        rows = [{"measured_at": p.measured_at, "local_date": p.local_date} for p in pts]
        if not _normalize_imported_chart_times(rows, force=force):
            self.stdout.write(
                f"Все {len(pts)} точек уже в последних 24 ч — сдвиг не нужен."
            )
            return
        for p, row in zip(pts, rows):
            p.measured_at = row["measured_at"]
            p.local_date = row["local_date"]
        AutoRefreshPoint.objects.bulk_update(pts, ["measured_at", "local_date"])
        t0 = min(p.measured_at for p in pts)
        t1 = max(p.measured_at for p in pts)
        self.stdout.write(
            self.style.SUCCESS(
                f"Пересчитано {len(pts)} точек: {timezone.localtime(t0)} … {timezone.localtime(t1)}"
            )
        )
