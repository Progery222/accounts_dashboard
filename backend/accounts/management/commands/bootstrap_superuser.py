"""
Идемпотентно создать/обновить Django-суперюзера из переменных окружения.

Зачем: на Railway нет интерактивного входа в контейнер, чтобы выполнить
``createsuperuser``. Команда читает env и обновляет пользователя при каждом
старте — удобно, чтобы один раз восстановить доступ к ``/admin/``, после
чего переменные можно удалить из Variables.

Переменные:
  DJANGO_SUPERUSER_USERNAME  — обязательная (если не задана, команда тихо
                                выходит и не падает; так удобно держать
                                вызов в Dockerfile CMD по умолчанию).
  DJANGO_SUPERUSER_PASSWORD  — обязательная при заданном username.
  DJANGO_SUPERUSER_EMAIL     — опциональная (по умолчанию пустой).

Поведение:
  - если пользователя нет — создаём суперюзера;
  - если есть — выставляем is_superuser/is_staff/is_active=True, обновляем
    email и пароль (set_password — будет хеширован).
"""
from __future__ import annotations

import os

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Create or update a Django superuser from DJANGO_SUPERUSER_* env."

    def handle(self, *args, **options):
        username = (os.environ.get("DJANGO_SUPERUSER_USERNAME") or "").strip()
        password = os.environ.get("DJANGO_SUPERUSER_PASSWORD") or ""
        email = (os.environ.get("DJANGO_SUPERUSER_EMAIL") or "").strip()

        if not username:
            self.stdout.write("[bootstrap_superuser] DJANGO_SUPERUSER_USERNAME не задан — пропуск.")
            return

        if not password:
            self.stderr.write("[bootstrap_superuser] DJANGO_SUPERUSER_PASSWORD пуст — отказ.")
            return

        User = get_user_model()
        user, created = User.objects.update_or_create(
            username=username,
            defaults={
                "is_superuser": True,
                "is_staff": True,
                "is_active": True,
                "email": email,
            },
        )
        user.set_password(password)
        user.save()
        action = "создан" if created else "обновлён"
        self.stdout.write(
            f"[bootstrap_superuser] {action}: id={user.pk} username={user.username} email={user.email!r}"
        )
