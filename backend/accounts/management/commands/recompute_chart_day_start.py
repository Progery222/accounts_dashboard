"""Пересчитать view_delta_from_day_start для AutoRefreshPoint (все дни или один)."""

from django.core.management.base import BaseCommand
from django.utils import timezone

from accounts.auto_refresh_pulse import recompute_day_start_for_local_date
from accounts.models import AutoRefreshPoint


class Command(BaseCommand):
    help = "Пересчитать накопленный прирост за сутки (view_delta_from_day_start) в точках графика Live."

    def add_arguments(self, parser):
        parser.add_argument(
            "--date",
            help="Календарный день YYYY-MM-DD (по умолчанию — все дни с точками).",
        )

    def handle(self, *args, **options):
        date_raw = (options.get("date") or "").strip()
        if date_raw:
            from datetime import date as date_cls

            target = date_cls.fromisoformat(date_raw)
            n = recompute_day_start_for_local_date(target)
            self.stdout.write(self.style.SUCCESS(f"{target}: обновлено {n} точек"))
            return

        total = 0
        dates = (
            AutoRefreshPoint.objects.order_by("local_date")
            .values_list("local_date", flat=True)
            .distinct()
        )
        for d in dates:
            total += recompute_day_start_for_local_date(d)
        self.stdout.write(self.style.SUCCESS(f"Обновлено {total} точек за {len(dates)} дней"))
