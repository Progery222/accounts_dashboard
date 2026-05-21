"""
Очистить данные TikTok в persistent-профиле Chromium (куки, state, IndexedDB и т.д.).

    py -3.13 -m poetry run python manage.py clear_tiktok_browser_data

Перед очисткой останавливает демоны Playwright и процессы Chrome для этого профиля.
"""
from __future__ import annotations

from django.core.management.base import BaseCommand

from accounts.settings_views import _get_profile_dir, _logout_platform
from platforms.worker_pool import shutdown_all_workers
from platforms.worker_utils import kill_chrome_processes_for_profile


class Command(BaseCommand):
    help = "Сбросить сессию TikTok в браузерном профиле дашборда (куки, storage, tiktok_state.json)."

    def handle(self, *args, **options):
        profile_dir = _get_profile_dir()
        self.stdout.write(f"Профиль Chromium: {profile_dir}")

        try:
            shutdown_all_workers()
            self.stdout.write("Демоны Playwright остановлены.")
        except Exception as exc:
            self.stdout.write(self.style.WARNING(f"shutdown_all_workers: {exc}"))

        try:
            kill_chrome_processes_for_profile(profile_dir)
            self.stdout.write("Процессы Chrome для профиля завершены.")
        except Exception as exc:
            self.stdout.write(self.style.WARNING(f"kill_chrome: {exc}"))

        _logout_platform("tiktok")
        self.stdout.write(
            self.style.SUCCESS(
                "Данные TikTok очищены. Подключите VPN, перезапустите вход в настройках "
                "(лучше через QR), не спешите с повторными попытками пароля."
            )
        )
