"""
Разовое выравнивание: если у Instagram/Threads account.view_count ниже опорного снимка
(как при «просевшем» парсинге), поднимаем до значения снимка — дельта просмотров станет 0.

По умолчанию только печатает строки; с --apply выполняет UPDATE.

Пример:
  python manage.py repair_instagram_view_totals
  python manage.py repair_instagram_view_totals --apply
"""

from __future__ import annotations

import datetime

from django.core.management.base import BaseCommand
from django.utils import timezone

from accounts.models import Account, AccountSnapshot, Platform, RefreshScheduleConfig


def _account_delta_period_days() -> int:
    try:
        cfg = RefreshScheduleConfig.get()
        d = int(getattr(cfg, "account_delta_period_days", 1) or 1)
    except Exception:
        return 1
    return d if d in (1, 7, 30) else 1


class Command(BaseCommand):
    help = "Поднять view_count аккаунта до опорного снимка, где текущее значение меньше baseline (Instagram/Threads)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Выполнить обновление в БД (без флага — только список кандидатов).",
        )

    def handle(self, *args, **options):
        apply: bool = options["apply"]
        today = timezone.localdate()
        period = _account_delta_period_days()
        cutoff = today - datetime.timedelta(days=period)
        changed = 0
        qs = Account.objects.filter(platform__in=(Platform.INSTAGRAM, Platform.THREADS)).only(
            "id", "platform", "username", "view_count",
        )
        for acc in qs.iterator():
            snap = (
                AccountSnapshot.objects.filter(account_id=acc.id, date__lte=cutoff)
                .order_by("-date")
                .only("date", "view_count")
                .first()
            )
            if snap is None:
                continue
            cur = int(acc.view_count or 0)
            base = int(snap.view_count or 0)
            if cur >= base:
                continue
            changed += 1
            self.stdout.write(
                f"{acc.platform}\t@{acc.username}\tview_count {cur} -> {base}\t(baseline {snap.date})",
            )
            if apply:
                Account.objects.filter(pk=acc.pk).update(view_count=base)
                AccountSnapshot.objects.filter(account_id=acc.pk, date=today).update(view_count=base)
        if changed == 0:
            self.stdout.write(self.style.SUCCESS("Нет аккаунтов с отрицательной дельтой по этому критерию."))
        elif apply:
            self.stdout.write(self.style.SUCCESS(f"Обновлено аккаунтов: {changed}"))
        else:
            self.stdout.write(
                self.style.WARNING(
                    f"Кандидатов: {changed}. Повторите с --apply для записи в БД.",
                ),
            )
