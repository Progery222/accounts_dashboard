"""
Прогрев сессии Facebook: только https://www.facebook.com/reel/

  cd backend
  py -3.13 -m poetry run python manage.py warm_facebook_session
"""
from __future__ import annotations

import asyncio
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from platforms.facebook.warm_session import FACEBOOK_REELS_URL, WarmFacebookConfig, run_warm_facebook_session
from platforms.tiktok.warm_session import WarmTikTokConfig, watch_duration_summary
from platforms.worker_pool import sync_accounts_browser_env


class Command(BaseCommand):
    help = (
        "Прогрев Facebook: только /reel/, 5–15 мин, просмотр и лайки как warm_tiktok."
    )

    def add_arguments(self, parser):
        parser.add_argument("--min-minutes", type=float, default=5.0)
        parser.add_argument("--max-minutes", type=float, default=15.0)
        parser.add_argument("--short-prob", type=float, default=0.7)
        parser.add_argument("--like-every-min", type=int, default=10)
        parser.add_argument("--like-every-max", type=int, default=30)
        parser.add_argument("--keep-open", action="store_true")
        parser.add_argument("--state-file", default="")

    def handle(self, *args, **options):
        applied = sync_accounts_browser_env()
        state_path = self._resolve_state_path(options.get("state_file") or "")
        if not state_path:
            raise CommandError(
                "Не найден путь для facebook_state.json. "
                "Задайте ACCOUNTS_BROWSER_PROFILE_DIR или --state-file."
            )

        min_m = float(options["min_minutes"])
        max_m = float(options["max_minutes"])
        if max_m < min_m:
            min_m, max_m = max_m, min_m

        like_min = max(1, int(options["like_every_min"]))
        like_max = max(like_min, int(options["like_every_max"]))

        cfg = WarmFacebookConfig(
            min_minutes=min_m,
            max_minutes=max_m,
            watch_short_prob=max(0.0, min(1.0, float(options["short_prob"]))),
            like_every_min=like_min,
            like_every_max=like_max,
            keep_browser_open=bool(options["keep_open"]),
        )

        watch_cfg = WarmTikTokConfig(watch_short_prob=cfg.watch_short_prob)

        if getattr(settings, "ACCOUNTS_BROWSER_HEADLESS", None):
            self.stdout.write(
                self.style.WARNING(
                    "ACCOUNTS_BROWSER_HEADLESS=true — для прогрева лучше false в worker_accounts.env",
                ),
            )

        self.stdout.write(f"Профиль Chrome: {Path(state_path).parent}")
        if applied.get("BROWSER_PROFILE_DIR"):
            self.stdout.write("  (ACCOUNTS_BROWSER_PROFILE_DIR)")
        self.stdout.write(f"Reels URL: {FACEBOOK_REELS_URL}")
        self.stdout.write(f"Сессия: {state_path}")
        self.stdout.write(
            f"Прогрев {cfg.min_minutes:.0f}–{cfg.max_minutes:.0f} мин, "
            f"просмотр: {watch_duration_summary(watch_cfg)}, "
            f"лайк каждые {like_min}–{like_max} роликов",
        )

        try:
            stats = asyncio.run(
                run_warm_facebook_session(cfg, state_path=Path(state_path)),
            )
        except KeyboardInterrupt:
            self.stdout.write(self.style.WARNING("Прервано."))
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

            return str(state_file_path("facebook", default_profile_dir()))
        except Exception:
            return ""
