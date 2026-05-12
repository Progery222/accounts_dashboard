"""
Разовое исправление: обнулить ошибочный like_count у постов Facebook
(типичный баг — в лайки попадало число просмотров).

По умолчанию только считает и печатает примеры; с --apply выполняет UPDATE
для Post и сегодняшних PostSnapshot.

Примеры:
  py -3.13 -m poetry run python manage.py repair_facebook_post_likes --like-equals-views
  py -3.13 -m poetry run python manage.py repair_facebook_post_likes --account-id 5 --match-like 158 --apply
"""

from __future__ import annotations

from functools import reduce
from operator import or_

from django.core.management.base import BaseCommand
from django.db.models import F, Q
from django.utils import timezone

from accounts.models import Platform, Post, PostSnapshot


class Command(BaseCommand):
    help = (
        "Обнулить like_count у постов Facebook по эвристикам "
        "(после ошибочного парсинга «просмотры как лайки»)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Выполнить обновление в БД (без флага — только dry-run).",
        )
        parser.add_argument(
            "--account-id",
            type=int,
            default=None,
            help="Ограничить посты одним аккаунтом (рекомендуется).",
        )
        parser.add_argument(
            "--like-equals-views",
            action="store_true",
            help="Посты, где like_count = view_count > 0 (частый признак ошибки).",
        )
        parser.add_argument(
            "--match-like",
            type=int,
            default=None,
            metavar="N",
            help="Посты с like_count == N, но view_count != N (например зависшее «158»).",
        )

    def handle(self, *args, **options):
        apply: bool = options["apply"]
        account_id = options["account_id"]
        like_eq_views: bool = options["like_equals_views"]
        match_like = options["match_like"]

        parts: list[Q] = []
        if like_eq_views:
            parts.append(
                Q(like_count=F("view_count"), view_count__gt=0, like_count__gt=0),
            )
        if match_like is not None:
            n = int(match_like)
            parts.append(Q(like_count=n) & ~Q(view_count=n))

        if not parts:
            self.stderr.write(
                "Укажите хотя бы один фильтр: --like-equals-views и/или --match-like N.\n",
            )
            return

        q = reduce(or_, parts)
        qs = Post.objects.filter(account__platform=Platform.FACEBOOK).filter(q)
        if account_id is not None:
            qs = qs.filter(account_id=account_id)

        total = qs.count()
        self.stdout.write(f"Кандидатов на обнуление like_count: {total}\n")
        if total == 0:
            self.stdout.write(self.style.SUCCESS("Нечего менять."))
            return

        for row in qs.order_by("id").values("id", "account_id", "external_id", "like_count", "view_count")[:25]:
            self.stdout.write(
                f"  post_id={row['id']}\taccount={row['account_id']}\text={row['external_id']!r}\t"
                f"likes={row['like_count']}\tviews={row['view_count']}\n",
            )
        if total > 25:
            self.stdout.write(f"  … и ещё {total - 25} пост(ов).\n")

        if not apply:
            self.stdout.write(
                self.style.WARNING("Dry-run. Повторите с --apply для записи в БД.\n"),
            )
            return

        today = timezone.localdate()
        ids = list(qs.values_list("id", flat=True))
        n_posts = Post.objects.filter(pk__in=ids).update(like_count=0)
        n_snaps = PostSnapshot.objects.filter(post_id__in=ids, date=today).update(like_count=0)
        self.stdout.write(
            self.style.SUCCESS(
                f"Обновлено постов: {n_posts}; снимков за {today}: {n_snaps}.",
            ),
        )
