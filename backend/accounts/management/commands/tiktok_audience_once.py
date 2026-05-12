"""Одиночный съём ников подписчиков TikTok через platforms/tiktok/worker.py."""
import asyncio

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = (
        "Съём списка подписчиков для одного @username через Playwright. "
        "Нужна сохранённая сессия TikTok (см. setup_tiktok_auth)."
    )

    def add_arguments(self, parser):
        parser.add_argument("username", help="Ник без @, например yllazenlab")
        parser.add_argument("--limit", type=int, default=50)
        parser.add_argument(
            "--max-posts",
            type=int,
            default=1,
            help="Сколько постов дотянуть с профиля каждого подписчика (1 — быстрее).",
        )
        parser.add_argument(
            "--save-db",
            action="store_true",
            help="Сохранить срез в БД (accounts): связи не из списка удалятся.",
        )

    def handle(self, *args, **options):
        from platforms.tiktok.worker import run_once

        uname = options["username"].lstrip("@").strip().lower()
        lim = max(1, min(int(options["limit"] or 50), 500))
        mpp = max(1, min(int(options["max_posts"] or 1), 80))
        payload = {
            "audience_followers": True,
            "username": uname,
            "limit": lim,
            "max_posts_per_follower": mpp,
        }
        result = asyncio.run(run_once(payload))
        if result.get("error"):
            self.stderr.write(f"{result['error']}\n")
            raise SystemExit(1)
        followers = result.get("followers") or []
        owner = result.get("owner_username") or uname
        self.stdout.write(f"Владелец: @{owner}\n")
        self.stdout.write(f"Записей: {len(followers)}\n")
        for row in followers:
            u = row.get("username") or ""
            if u:
                self.stdout.write(f"@{u}\n")

        if options.get("save_db"):
            from accounts.audience import sync_audience_from_payload
            from accounts.models import Account, Platform

            acc = Account.objects.filter(username=uname, platform=Platform.TIKTOK).first()
            if not acc:
                self.stderr.write(
                    f"Аккаунт TikTok @{uname} не найден в БД — пропуск сохранения (--save-db).\n",
                )
                return
            sync = sync_audience_from_payload(acc, result)
            self.stdout.write(
                f"БД: сохранено подписчиков {sync.get('followers_saved', 0)}, "
                f"синхронизация {sync.get('synced_at', '')}\n",
            )
