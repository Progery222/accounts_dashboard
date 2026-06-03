"""
Удалить данные дашборда (аккаунты, посты, снимки, профили, аудитория, точки графиков).
Не трогает: пользователей Django, расписание (RefreshScheduleConfig), видимость платформ.

  python manage.py clear_dashboard_data --dry-run
  python manage.py clear_dashboard_data --yes
"""
from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Count

from accounts.models import (
    Account,
    AccountAudienceMembership,
    AccountSnapshot,
    AudienceMember,
    AudienceMemberPost,
    AutoRefreshPoint,
    AutoRefreshState,
    Post,
    PostSnapshot,
    Profile,
    RefreshAllState,
)


class Command(BaseCommand):
    help = "Очистить аккаунты, профили, посты, снимки и аудиторию для чистого импорта."

    def add_arguments(self, parser):
        parser.add_argument(
            "--yes",
            action="store_true",
            help="Выполнить удаление (без флага — только отчёт).",
        )
        parser.add_argument(
            "--keep-profiles",
            action="store_true",
            help="Не удалять профили (только аккаунты и связанные данные).",
        )

    def handle(self, *args, **options):
        dry_run = not options["yes"]
        keep_profiles = options["keep_profiles"]

        counts = {
            "post_snapshots": PostSnapshot.objects.count(),
            "posts": Post.objects.count(),
            "account_snapshots": AccountSnapshot.objects.count(),
            "audience_memberships": AccountAudienceMembership.objects.count(),
            "audience_member_posts": AudienceMemberPost.objects.count(),
            "audience_members": AudienceMember.objects.count(),
            "accounts": Account.objects.count(),
            "profiles": Profile.objects.count(),
            "auto_refresh_points": AutoRefreshPoint.objects.count(),
        }
        self.stdout.write("Будет удалено:")
        for k, v in counts.items():
            self.stdout.write(f"  {k}: {v}")

        if dry_run:
            self.stdout.write(
                self.style.WARNING("Dry-run. Для удаления: manage.py clear_dashboard_data --yes")
            )
            return

        with transaction.atomic():
            PostSnapshot.objects.all().delete()
            Post.objects.all().delete()
            AccountSnapshot.objects.all().delete()
            AccountAudienceMembership.objects.all().delete()
            AudienceMemberPost.objects.all().delete()
            AudienceMember.objects.all().delete()
            Account.objects.all().delete()
            AutoRefreshPoint.objects.all().delete()
            if not keep_profiles:
                Profile.objects.all().delete()

            for model in (AutoRefreshState, RefreshAllState):
                obj = model.get()
                obj.is_running = False
                obj.cancel_requested = False
                obj.total_accounts = 0
                obj.processed_accounts = 0
                obj.success_accounts = 0
                obj.failed_accounts = 0
                obj.current_account = ""
                obj.started_at = None
                obj.finished_at = None
                obj.last_error = ""
                obj.last_report_csv = ""
                obj.last_report_generated_at = None
                obj.run_detail = {}
                if hasattr(obj, "last_auto_refresh_error_account_ids"):
                    obj.last_auto_refresh_error_account_ids = []
                if hasattr(obj, "last_telegram_error"):
                    obj.last_telegram_error = ""
                    obj.last_telegram_sent_at = None
                if hasattr(obj, "source"):
                    obj.source = "scheduler"
                obj.save()

        self.stdout.write(self.style.SUCCESS("Данные дашборда удалены."))
        if keep_profiles:
            self.stdout.write(f"Профили сохранены: {Profile.objects.count()}")
        else:
            self.stdout.write(f"Профилей осталось: {Profile.objects.count()}")
        self.stdout.write(f"Аккаунтов осталось: {Account.objects.count()}")
