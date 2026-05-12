"""
Полный сброс данных Facebook в БД перед массовым обновлением:

- удаляет все Post и PostSnapshot для аккаунтов platform=facebook (CASCADE);
- удаляет все AccountSnapshot для этих аккаунтов;
- обнуляет счётчики на Account: follower_count, like_count, view_count, post_count.

По умолчанию dry-run. Запись: --apply

Пример:
  py -3.13 -m poetry run python manage.py reset_facebook_posts_and_counters --apply
"""

from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db import transaction

from accounts.models import Account, AccountSnapshot, Platform, Post, PostSnapshot


class Command(BaseCommand):
    help = "Удалить посты/снимки постов Facebook и обнулить счётчики аккаунтов Facebook."

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Выполнить удаление и UPDATE (без флага — только отчёт).",
        )

    def handle(self, *args, **options):
        apply: bool = options["apply"]

        acc_ids = list(
            Account.objects.filter(platform=Platform.FACEBOOK).values_list("id", flat=True),
        )
        n_acc = len(acc_ids)
        if n_acc == 0:
            self.stdout.write(self.style.SUCCESS("Нет аккаунтов Facebook — нечего делать."))
            return

        post_qs = Post.objects.filter(account_id__in=acc_ids)
        n_posts = post_qs.count()
        n_post_snaps = PostSnapshot.objects.filter(post__account_id__in=acc_ids).count()
        n_acc_snaps = AccountSnapshot.objects.filter(account_id__in=acc_ids).count()

        self.stdout.write(
            f"Аккаунтов Facebook: {n_acc}\n"
            f"Постов к удалению: {n_posts}\n"
            f"Снимков постов: {n_post_snaps}\n"
            f"Снимков аккаунтов: {n_acc_snaps}\n"
            f"Счётчики аккаунтов будут обнулены (followers / likes / views / post_count).\n",
        )

        if not apply:
            self.stdout.write(self.style.WARNING("Dry-run. Повторите с --apply для записи в БД.\n"))
            return

        with transaction.atomic():
            deleted_posts, _ = post_qs.delete()
            acc_snap_deleted, _ = AccountSnapshot.objects.filter(account_id__in=acc_ids).delete()
            updated = Account.objects.filter(platform=Platform.FACEBOOK).update(
                follower_count=0,
                like_count=0,
                view_count=0,
                post_count=0,
            )

        self.stdout.write(
            self.style.SUCCESS(
                f"Готово. Удалено объектов (агрегат delete): {deleted_posts}; "
                f"снимков аккаунтов удалено строк: {acc_snap_deleted}; "
                f"аккаунтов обновлено: {updated}.",
            ),
        )
