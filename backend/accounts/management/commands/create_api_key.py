"""Создать ключ внешнего API (Bearer). Сырой токен печатается один раз."""
from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from accounts.api_auth import generate_api_key
from accounts.models import Domain, ExternalApiKey, ExternalApiKeyScope


class Command(BaseCommand):
    help = "Создать ExternalApiKey и вывести Bearer-токен (один раз)."

    def add_arguments(self, parser):
        parser.add_argument("--name", required=True, help="Имя интеграции / сервиса")
        parser.add_argument(
            "--scopes",
            default="read",
            help="Через запятую: read,write,refresh,export (по умолчанию read)",
        )
        parser.add_argument("--domain", default="", help="slug домена (опционально)")

    def handle(self, *args, **options):
        name = (options["name"] or "").strip()
        if not name:
            raise CommandError("--name обязателен")

        allowed = {c.value for c in ExternalApiKeyScope}
        scopes = []
        for part in (options["scopes"] or "").split(","):
            s = part.strip().lower()
            if not s:
                continue
            if s not in allowed:
                raise CommandError(f"Неизвестный scope «{s}». Допустимо: {', '.join(sorted(allowed))}")
            if s not in scopes:
                scopes.append(s)
        if not scopes:
            raise CommandError("Нужен хотя бы один scope")

        domain = None
        slug = (options["domain"] or "").strip().lower()
        if slug:
            domain = Domain.objects.filter(slug=slug, is_active=True).first()
            if domain is None:
                raise CommandError(f"Домен «{slug}» не найден или выключен")

        raw, prefix, key_hash = generate_api_key()
        ExternalApiKey.objects.create(
            name=name,
            key_prefix=prefix,
            key_hash=key_hash,
            scopes=scopes,
            domain=domain,
        )
        self.stdout.write(self.style.SUCCESS(f"Ключ создан: {name} ({prefix}…) scopes={scopes}"))
        if domain:
            self.stdout.write(f"Домен: /{domain.slug}")
        self.stdout.write("")
        self.stdout.write(self.style.WARNING("Сохраните токен — повторно показать нельзя:"))
        self.stdout.write(raw)
