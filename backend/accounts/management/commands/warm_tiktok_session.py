"""
Прогрев сессии TikTok перед массовым съёмом (снижает 403/капчу).

Примеры:
    cd backend
    py -3.13 -m poetry run python manage.py warm_tiktok_session
    py -3.13 -m poetry run python manage.py warm_tiktok_session --min-minutes 8 --max-minutes 20
    py -3.13 -m poetry run python manage.py warm_tiktok_session --feed following
    py -3.13 -m poetry run python manage.py warm_tiktok_session --close
"""
from __future__ import annotations

import asyncio
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from platforms.tiktok.warm_session import (
    WarmTikTokConfig,
    run_warm_tiktok_session,
    watch_duration_summary,
)
from platforms.worker_pool import sync_accounts_browser_env


class Command(BaseCommand):
    help = (
        "Прогрев TikTok: лента 5–25 мин, просмотр 70%×(1–6 с) и 30%×(20–45 с), редкие лайки. "
        "Тот же Chrome и tiktok_state.json, что у worker."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--min-minutes",
            type=float,
            default=5.0,
            help="Минимальная длительность прогрева (мин).",
        )
        parser.add_argument(
            "--max-minutes",
            type=float,
            default=25.0,
            help="Максимальная длительность прогрева (мин).",
        )
        parser.add_argument(
            "--short-prob",
            type=float,
            default=0.7,
            help="Доля коротких просмотров (1–6 с), по умолчанию 0.7.",
        )
        parser.add_argument(
            "--long-prob",
            type=float,
            default=None,
            help="Доля длинных просмотров (20–45 с); по умолчанию 1 − short-prob.",
        )
        parser.add_argument(
            "--like-every-min",
            type=int,
            default=10,
            help="Лайк не чаще чем раз в N роликов (нижняя граница интервала).",
        )
        parser.add_argument(
            "--like-every-max",
            type=int,
            default=30,
            help="Лайк не чаще чем раз в N роликов (верхняя граница интервала).",
        )
        parser.add_argument(
            "--feed",
            choices=("foryou", "following", "home"),
            default="foryou",
            help="Какую ленту открыть (по умолчанию For You).",
        )
        parser.add_argument(
            "--close",
            action="store_true",
            help="Закрыть браузер после прогрева (по умолчанию окно остаётся открытым).",
        )
        parser.add_argument(
            "--state-file",
            default="",
            help="Куда сохранить storage_state (по умолчанию <профиль>/tiktok_state.json).",
        )

    def handle(self, *args, **options):
        applied = sync_accounts_browser_env()
        from accounts.refresh_state import clear_stale_refresh_runs_if_needed
        from accounts.models import AutoRefreshState, RefreshAllState

        cleared = clear_stale_refresh_runs_if_needed()
        auto = AutoRefreshState.get()
        rr = RefreshAllState.get()
        if auto.is_running or rr.is_running:
            raise CommandError(
                "Сейчас идёт автообновление или «собрать всех». "
                "Остановите в UI или подождите; после warm_tiktok старый прогон мог зависнуть — "
                "обновите страницу (статус сбросится через 4 ч без прогресса) или: "
                "python manage.py clear_refresh_run_state",
            )
        if cleared:
            self.stdout.write(
                self.style.WARNING(
                    f"Сброшен зависший прогон: {', '.join(cleared)}",
                ),
            )
        state_path = self._resolve_state_path(options.get("state_file") or "")
        if not state_path:
            raise CommandError(
                "Не найден путь для tiktok_state.json. "
                "Задайте ACCOUNTS_BROWSER_PROFILE_DIR / BROWSER_PROFILE_DIR в .env "
                "или --state-file."
            )

        min_m = float(options["min_minutes"])
        max_m = float(options["max_minutes"])
        if max_m < min_m:
            min_m, max_m = max_m, min_m

        like_min = max(1, int(options["like_every_min"]))
        like_max = max(like_min, int(options["like_every_max"]))

        short_prob = max(0.0, min(1.0, float(options["short_prob"])))
        long_prob_raw = options.get("long_prob")
        if long_prob_raw is not None:
            short_prob = max(0.0, min(1.0, 1.0 - float(long_prob_raw)))
        cfg = WarmTikTokConfig(
            min_minutes=min_m,
            max_minutes=max_m,
            watch_short_prob=short_prob,
            like_every_min=like_min,
            like_every_max=like_max,
            feed=str(options["feed"]),
            keep_browser_open=not bool(options["close"]),
        )

        headless = getattr(settings, "ACCOUNTS_BROWSER_HEADLESS", None)
        if headless is None:
            import os
            headless = os.environ.get("BROWSER_HEADLESS", "").lower() in {
                "1", "true", "yes", "on",
            }
        if headless:
            self.stdout.write(
                self.style.WARNING(
                    "BROWSER_HEADLESS=true — для капчи и прогрева лучше "
                    "ACCOUNTS_BROWSER_HEADLESS=false в worker_accounts.env",
                ),
            )

        prof_dir = str(Path(state_path).parent)
        self.stdout.write(f"Профиль Chrome: {prof_dir}")
        if applied.get("BROWSER_PROFILE_DIR"):
            self.stdout.write(
                f"  (из ACCOUNTS_BROWSER_PROFILE_DIR → BROWSER_PROFILE_DIR)",
            )
        self.stdout.write(f"Сохранение сессии: {state_path}")
        if not Path(state_path).exists():
            self.stdout.write(
                self.style.WARNING(
                    "tiktok_state.json ещё нет — прогрев откроет пустой браузер. "
                    "Сначала импортируйте cookies в Настройках → TikTok.",
                ),
            )
        self.stdout.write(
            f"Прогрев {cfg.min_minutes:.0f}–{cfg.max_minutes:.0f} мин, лента={cfg.feed}, "
            f"просмотр: {watch_duration_summary(cfg)}",
        )
        if cfg.keep_browser_open:
            self.stdout.write(
                "После прогрева окно Chrome останется открытым (Ctrl+C — выход из команды). "
                "Чтобы закрыть автоматически: --close",
            )

        try:
            stats = asyncio.run(
                run_warm_tiktok_session(cfg, state_path=Path(state_path)),
            )
        except KeyboardInterrupt:
            self.stdout.write(self.style.WARNING("Прервано пользователем."))
            return

        self.stdout.write(
            self.style.SUCCESS(
                f"Готово: ~{stats['duration_sec'] / 60:.1f} мин, "
                f"роликов ~{stats['videos']}, лайков {stats['likes']}. "
                f"State: {stats['state_path']}",
            ),
        )

    def _resolve_state_path(self, override: str) -> str:
        if override.strip():
            return str(Path(override).expanduser())
        try:
            from platforms.worker_utils import default_profile_dir, state_file_path

            return str(state_file_path("tiktok", default_profile_dir()))
        except Exception:
            return ""
