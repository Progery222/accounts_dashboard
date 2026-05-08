"""
One-time TikTok browser login and cookie export.

Usage:
    python manage.py setup_tiktok_auth
    python manage.py setup_tiktok_auth --server --check-refresh

Opens a visible Chromium window and navigates to TikTok login page.
Optional --autofill pre-fills TIKTOK_USERNAME / TIKTOK_PASSWORD from settings.
Complete any CAPTCHA / 2FA in the browser window, then press Enter here.
Cookies are exported to BROWSER_STATE_FILE (локальный путь) или, в server-режиме,
в <BROWSER_PROFILE_DIR>/tiktok_state.json.
"""
import asyncio
import os
import subprocess
import time
from pathlib import Path
from django.core.management.base import BaseCommand, CommandError
from django.conf import settings


class Command(BaseCommand):
    help = "Открыть браузер для входа в TikTok и экспортировать куки (выполняется один раз)"

    def add_arguments(self, parser):
        parser.add_argument(
            "--server",
            action="store_true",
            help="Режим VPS/Docker: state сохраняется в <BROWSER_PROFILE_DIR>/tiktok_state.json, при необходимости поднимается Xvfb.",
        )
        parser.add_argument(
            "--display",
            default=":99",
            help="DISPLAY для Xvfb в server-режиме (по умолчанию :99).",
        )
        parser.add_argument(
            "--check-refresh",
            action="store_true",
            help="После сохранения state выполнить тестовый refresh одного TikTok-аккаунта.",
        )
        parser.add_argument(
            "--account-id",
            type=int,
            default=None,
            help="ID TikTok-аккаунта для тестового refresh.",
        )
        parser.add_argument(
            "--username",
            default="",
            help="Username TikTok-аккаунта для тестового refresh (если не указан --account-id).",
        )
        parser.add_argument(
            "--autofill",
            action="store_true",
            help="Автозаполнить логин/пароль в форме (без автоклика по кнопке входа).",
        )

    def handle(self, *args, **options):
        server_mode = bool(options.get("server"))
        state_file = self._resolve_state_file(server_mode=server_mode)
        if not state_file:
            raise CommandError(
                "Укажи BROWSER_STATE_FILE в .env — путь к файлу куков.\n"
                "Например: BROWSER_STATE_FILE=tiktok_state.json"
            )

        username = getattr(settings, "TIKTOK_USERNAME", "")
        password = getattr(settings, "TIKTOK_PASSWORD", "")
        autofill = bool(options.get("autofill"))

        self.stdout.write("Открываю браузер и перехожу на страницу входа TikTok…")
        if autofill and username:
            self.stdout.write(f"Буду заполнять логин: {username}")
        self.stdout.write(f"Куки будут сохранены в: {state_file}\n")

        asyncio.run(
            self._run(
                state_file=state_file,
                username=username,
                password=password,
                autofill=autofill,
                server_mode=server_mode,
                display=str(options.get("display") or ":99"),
            )
        )
        if options.get("check_refresh"):
            self._check_refresh(
                account_id=options.get("account_id"),
                account_username=(options.get("username") or "").strip(),
            )

    def _resolve_state_file(self, *, server_mode: bool) -> str:
        profile_dir = getattr(settings, "BROWSER_PROFILE_DIR", "")
        if server_mode:
            if not profile_dir:
                raise CommandError("Для --server укажи BROWSER_PROFILE_DIR в .env.")
            return str(Path(profile_dir) / "tiktok_state.json")
        state_file = getattr(settings, "BROWSER_STATE_FILE", "")
        if state_file:
            return state_file
        if profile_dir:
            # Безопасный fallback: чтобы команда работала даже без BROWSER_STATE_FILE.
            return str(Path(profile_dir) / "tiktok_state.json")
        return ""

    async def _run(
        self,
        *,
        state_file: str,
        username: str,
        password: str,
        autofill: bool,
        server_mode: bool,
        display: str,
    ):
        from playwright.async_api import async_playwright

        xvfb_proc = None
        if server_mode and not os.environ.get("DISPLAY"):
            xvfb_proc = self._start_xvfb(display=display)
            os.environ["DISPLAY"] = display

        async with async_playwright() as pw:
            try:
                browser = await pw.chromium.launch(
                    headless=False,
                    args=["--disable-blink-features=AutomationControlled"],
                )
                context = await browser.new_context(
                    locale="en-US",
                    viewport={"width": 1280, "height": 900},
                )
                page = await context.new_page()

                # Open generic login page so user can choose QR / phone / email.
                await page.goto(
                    "https://www.tiktok.com/login",
                    wait_until="domcontentloaded",
                )
                await page.wait_for_timeout(2000)

                if autofill and username:
                    try:
                        # Fill username field
                        user_sel = 'input[name="username"], input[placeholder*="email" i], input[autocomplete="username"]'
                        await page.wait_for_selector(user_sel, timeout=8000)
                        await page.fill(user_sel, username)
                        await page.wait_for_timeout(500)
                    except Exception:
                        self.stdout.write(self.style.WARNING("Не удалось найти поле логина — заполни вручную."))

                if autofill and password:
                    try:
                        pass_sel = 'input[type="password"]'
                        await page.wait_for_selector(pass_sel, timeout=5000)
                        await page.fill(pass_sel, password)
                    except Exception:
                        self.stdout.write(self.style.WARNING("Не удалось заполнить пароль — введи вручную."))

                self.stdout.write(
                    "\nЕсли появилась капча или 2FA — пройди их в браузере.\n"
                    "Когда вход завершён — нажми Enter здесь."
                )
                await asyncio.get_event_loop().run_in_executor(None, input)

                Path(state_file).parent.mkdir(parents=True, exist_ok=True)
                await context.storage_state(path=state_file)
                await browser.close()
            finally:
                if xvfb_proc:
                    xvfb_proc.terminate()
                    try:
                        xvfb_proc.wait(timeout=5)
                    except Exception:
                        xvfb_proc.kill()

        self.stdout.write(self.style.SUCCESS(
            f"\nКуки сохранены в {state_file}\n"
            "На проде поместите этот файл (или переименуйте) в каталог профиля:\n"
            "  <BROWSER_PROFILE_DIR>/tiktok_state.json\n"
            "Например в Docker/Railway: /app/.browser-profile/tiktok_state.json "
            "(volume на этот каталог).\n"
            "Переменная BROWSER_STATE_FILE на сервере для воркера TikTok не "
            "нужна, если файл лежит по пути выше."
        ))

    def _start_xvfb(self, *, display: str):
        cmd = ["Xvfb", display, "-screen", "0", "1366x768x24", "-nolisten", "tcp", "-ac"]
        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except FileNotFoundError as exc:
            raise CommandError(
                "Xvfb не найден. Установи пакет xvfb и повтори команду в --server режиме."
            ) from exc
        time.sleep(0.8)
        if proc.poll() is not None:
            raise CommandError("Не удалось запустить Xvfb (процесс завершился сразу).")
        self.stdout.write(f"Запущен Xvfb на DISPLAY={display}")
        return proc

    def _check_refresh(self, *, account_id: int | None, account_username: str):
        from accounts.models import Account, Platform
        from accounts.views import _apply_refresh

        qs = Account.objects.filter(platform=Platform.TIKTOK).order_by("id")
        if account_id:
            account = qs.filter(id=account_id).first()
            if not account:
                raise CommandError(f"TikTok-аккаунт с id={account_id} не найден.")
        elif account_username:
            account = qs.filter(username=account_username).first()
            if not account:
                raise CommandError(f"TikTok-аккаунт @{account_username} не найден.")
        else:
            account = qs.first()
            if not account:
                self.stdout.write(self.style.WARNING("TikTok-аккаунтов в БД нет: refresh-пробу пропускаю."))
                return

        before_posts = account.posts.count()
        self.stdout.write(f"Пробую refresh для @{account.username} (id={account.id})…")
        try:
            refreshed = _apply_refresh(account)
        except Exception as exc:
            raise CommandError(f"Refresh после логина завершился ошибкой: {exc}") from exc
        after_posts = refreshed.posts.count()
        self.stdout.write(
            self.style.SUCCESS(
                "Refresh завершён. "
                f"Постов до: {before_posts}, после: {after_posts}."
            )
        )
