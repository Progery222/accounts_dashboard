"""Заполнить разбивку старых точек AutoRefreshPoint по данным AccountSnapshot.

Поля ``domain_totals`` и ``account_totals`` появились позже самих точек, поэтому
у записанных до этого разбивки нет — и живой счётчик внутри домена или на срезе
стоит, пока обе опорные точки не обзаведутся ею (примерно сутки).

Ждать не обязательно: измерения за прошлые дни уже лежат в снимках. Для точки в
момент M берём состояние на конец предыдущего дня — именно оно и было последним
известным на 10:00 этого дня, когда вечерний прогон текущих суток ещё не шёл.
Числа настоящие, замеренные; выдуманных опор здесь нет.

    manage.py backfill_point_breakdowns --days 3
    manage.py backfill_point_breakdowns --days 3 --dry-run

По умолчанию не трогает точки, у которых разбивка уже есть: свежие пишет сам
пульс, и они точнее снимков.
"""

from __future__ import annotations

import datetime

from django.core.management.base import BaseCommand
from django.utils import timezone

from accounts.models import Account, AccountSnapshot, AutoRefreshPoint


def _views_as_of(day) -> dict[str, int]:
    """Просмотры по аккаунтам на конец дня ``day`` — последний снимок каждого."""
    rows = (
        AccountSnapshot.objects.filter(date__lte=day)
        .order_by("account_id", "-date")
        .distinct("account_id")
        .values("account_id", "view_count")
    )
    return {str(r["account_id"]): int(r["view_count"] or 0) for r in rows}


def _by_domain(account_totals: dict[str, int]) -> dict[str, int]:
    domain_of = {
        str(pk): (str(dom) if dom else "none")
        for pk, dom in Account.objects.values_list("id", "domain_id")
    }
    out: dict[str, int] = {}
    for acc_id, val in account_totals.items():
        key = domain_of.get(acc_id, "none")
        out[key] = out.get(key, 0) + int(val or 0)
    return out


class Command(BaseCommand):
    help = "Заполнить domain_totals/account_totals у точек по снимкам за прошлые дни."

    def add_arguments(self, parser):
        parser.add_argument("--days", type=int, default=3, help="Сколько суток назад обрабатывать.")
        parser.add_argument("--dry-run", action="store_true", help="Показать, ничего не записывая.")
        parser.add_argument(
            "--overwrite",
            action="store_true",
            help="Перезаписать и там, где разбивка уже есть (обычно не нужно).",
        )

    def handle(self, *args, **opts):
        days = max(1, int(opts["days"]))
        dry = bool(opts["dry_run"])
        overwrite = bool(opts["overwrite"])
        since = timezone.now() - datetime.timedelta(days=days)

        points = list(AutoRefreshPoint.objects.filter(measured_at__gte=since).order_by("measured_at"))
        if not points:
            self.stdout.write("Точек за период нет.")
            return

        cache: dict[datetime.date, dict[str, int]] = {}
        touched = skipped = empty = 0
        for p in points:
            if not overwrite and (p.account_totals or p.domain_totals):
                skipped += 1
                continue
            local = timezone.localtime(p.measured_at)
            day = local.date() - datetime.timedelta(days=1)
            if day not in cache:
                cache[day] = _views_as_of(day)
            acc = cache[day]
            if not acc:
                empty += 1
                continue
            dom = _by_domain(acc)
            self.stdout.write(
                f"{local:%m-%d %H:%M} {p.source:<10} ← снимки на {day}: "
                f"{len(acc)} акк., {len(dom)} доменов, сумма {sum(acc.values())}"
            )
            if not dry:
                p.account_totals = acc
                p.domain_totals = dom
                p.save(update_fields=["account_totals", "domain_totals"])
            touched += 1

        verb = "показано" if dry else "записано"
        self.stdout.write(
            self.style.SUCCESS(
                f"{verb}: {touched}; пропущено (уже с разбивкой): {skipped}; без снимков: {empty}"
            )
        )
