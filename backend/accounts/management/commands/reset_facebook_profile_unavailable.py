"""
Сбросить «профиль недоступен» у Facebook после ложного срабатывания на rate limit.

  python manage.py reset_facebook_profile_unavailable
  python manage.py reset_facebook_profile_unavailable --apply
"""

from __future__ import annotations

import itertools

from django.core.management.base import BaseCommand

from accounts.models import Account, Platform


class Command(BaseCommand):
    help = "Снять profile_unavailable у аккаунтов platform=facebook."

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Выполнить UPDATE в БД.",
        )

    def handle(self, *args, **options):
        apply: bool = options["apply"]
        qs = Account.objects.filter(
            platform=Platform.FACEBOOK,
            profile_unavailable=True,
        )
        n = qs.count()
        if n == 0:
            self.stdout.write(self.style.SUCCESS("Нет аккаунтов Facebook с profile_unavailable=True."))
            return
        self.stdout.write(f"Найдено аккаунтов Facebook с «недоступен»: {n}")
        if not apply:
            for a in itertools.islice(qs.only("id", "username").iterator(), 50):
                self.stdout.write(f"  id={a.id} @{a.username}")
            if n > 50:
                self.stdout.write(f"  … и ещё {n - 50}")
            self.stdout.write(self.style.WARNING("Повторите с --apply для записи в БД."))
            return
        updated = qs.update(profile_unavailable=False)
        self.stdout.write(self.style.SUCCESS(f"Обновлено записей: {updated}"))
