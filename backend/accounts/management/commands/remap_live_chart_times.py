"""Сдвинуть measured_at точек Live-графика в последние 24 ч (после импорта со старыми метками)."""

from django.core.management.base import BaseCommand
from django.utils import timezone

from accounts.models import AutoRefreshPoint
from accounts.snapshot_io import _normalize_imported_chart_times, _normalize_imported_chart_totals


class Command(BaseCommand):
    help = "Пересчитать measured_at AutoRefreshPoint в окно последних 24 часов."

    def add_arguments(self, parser):
        parser.add_argument(
            "--force",
            action="store_true",
            help="Всегда раскладывать все точки по 24 ч (даже если разброс нормальный).",
        )
        parser.add_argument(
            "--rebuild-totals",
            action="store_true",
            help="Пересобрать view_count_total по дельтам (даже если spread выглядит нормальным).",
        )

    def handle(self, *args, **options):
        force = bool(options.get("force"))
        rebuild_totals = bool(options.get("rebuild_totals"))
        pts = list(AutoRefreshPoint.objects.order_by("measured_at"))
        if not pts:
            self.stdout.write("Точек нет — нечего пересчитывать.")
            return
        rows = [
            {
                "measured_at": p.measured_at,
                "local_date": p.local_date,
                "view_count_total": p.view_count_total,
                "view_delta_from_prev_point": p.view_delta_from_prev_point,
                "view_delta_from_day_start": p.view_delta_from_day_start,
                "platform_deltas": dict(p.platform_deltas or {}),
            }
            for p in pts
        ]
        times_changed = _normalize_imported_chart_times(rows, force=force)
        totals_changed = _normalize_imported_chart_totals(
            rows,
            force=force or rebuild_totals,
        )
        if not times_changed and not totals_changed:
            self.stdout.write(
                f"Все {len(pts)} точек уже в порядке (время и totals) — пересчёт не нужен."
            )
            return
        update_fields = ["measured_at", "local_date"]
        if totals_changed:
            update_fields.extend(
                [
                    "view_count_total",
                    "view_delta_from_prev_point",
                    "view_delta_from_day_start",
                    "platform_deltas",
                ],
            )
        for p, row in zip(pts, rows):
            p.measured_at = row["measured_at"]
            p.local_date = row["local_date"]
            if totals_changed:
                p.view_count_total = row["view_count_total"]
                p.view_delta_from_prev_point = row["view_delta_from_prev_point"]
                p.view_delta_from_day_start = row["view_delta_from_day_start"]
        AutoRefreshPoint.objects.bulk_update(pts, update_fields)
        t0 = min(p.measured_at for p in pts)
        t1 = max(p.measured_at for p in pts)
        self.stdout.write(
            self.style.SUCCESS(
                f"Пересчитано {len(pts)} точек: {timezone.localtime(t0)} … {timezone.localtime(t1)}"
            )
        )
