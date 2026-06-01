"""Отладка: refresh одного аккаунта через Apify."""
from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from accounts.models import Account
from accounts.scrape_backend import should_use_apify_for_account
from platforms.apify.config import apify_enabled
from platforms.apify.dispatch import dispatch_apify_refresh


class Command(BaseCommand):
    help = "Запустить Apify refresh для account id (ожидание через poller/webhook)."

    def add_arguments(self, parser):
        parser.add_argument("account_id", type=int)

    def handle(self, *args, **options):
        if not apify_enabled():
            raise CommandError("Apify отключён (APIFY_ENABLED / APIFY_TOKEN)")
        account = Account.objects.get(pk=options["account_id"])
        if not should_use_apify_for_account(account):
            raise CommandError(
                f"Для {account.platform} в ScrapeBackendConfig не выбран apify. "
                "Переключите в /api/settings/scrape-backend/ или админке."
            )
        job = dispatch_apify_refresh(account)
        self.stdout.write(
            self.style.SUCCESS(
                f"job_id={job.pk} status={job.status} run_id={job.apify_run_id!r} "
                f"(завершение — poller/webhook)"
            )
        )
