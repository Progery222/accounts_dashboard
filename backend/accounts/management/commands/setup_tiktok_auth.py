"""
One-time TikTok browser login and cookie export.

Usage:
    python manage.py setup_tiktok_auth

Opens a visible Chromium window, navigates to the TikTok login page and
auto-fills TIKTOK_USERNAME / TIKTOK_PASSWORD from settings (if set).
Complete any CAPTCHA / 2FA in the browser window, then press Enter here.
Cookies are exported to BROWSER_STATE_FILE.

On the server set:
    BROWSER_HEADLESS=true
    BROWSER_STATE_FILE=/app/tiktok_state.json
"""
import asyncio
from pathlib import Path
from django.core.management.base import BaseCommand, CommandError
from django.conf import settings


class Command(BaseCommand):
    help = "Открыть браузер для входа в TikTok и экспортировать куки (выполняется один раз)"

    def handle(self, *args, **options):
        state_file = getattr(settings, "BROWSER_STATE_FILE", "")
        if not state_file:
            raise CommandError(
                "Укажи BROWSER_STATE_FILE в .env — путь к файлу куков.\n"
                "Например: BROWSER_STATE_FILE=tiktok_state.json"
            )

        username = getattr(settings, "TIKTOK_USERNAME", "")
        password = getattr(settings, "TIKTOK_PASSWORD", "")

        self.stdout.write("Открываю браузер и перехожу на страницу входа TikTok…")
        if username:
            self.stdout.write(f"Буду заполнять логин: {username}")
        self.stdout.write(f"Куки будут сохранены в: {state_file}\n")

        asyncio.run(self._run(state_file, username, password))

    async def _run(self, state_file: str, username: str, password: str):
        from playwright.async_api import async_playwright

        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=False)
            context = await browser.new_context(
                locale="en-US",
                viewport={"width": 1280, "height": 900},
            )
            page = await context.new_page()

            # Go straight to username/password login form
            await page.goto(
                "https://www.tiktok.com/login/phone-or-email/email",
                wait_until="domcontentloaded",
            )
            await page.wait_for_timeout(2000)

            if username:
                try:
                    # Fill username field
                    user_sel = 'input[name="username"], input[placeholder*="email" i], input[autocomplete="username"]'
                    await page.wait_for_selector(user_sel, timeout=8000)
                    await page.fill(user_sel, username)
                    await page.wait_for_timeout(500)
                except Exception:
                    self.stdout.write(self.style.WARNING("Не удалось найти поле логина — заполни вручную."))

            if password:
                try:
                    pass_sel = 'input[type="password"]'
                    await page.wait_for_selector(pass_sel, timeout=5000)
                    await page.fill(pass_sel, password)
                    await page.wait_for_timeout(500)
                    # Click the login button
                    btn_sel = 'button[type="submit"], button[data-e2e="login-button"]'
                    btn = page.locator(btn_sel).first
                    if await btn.is_visible():
                        await btn.click()
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

        self.stdout.write(self.style.SUCCESS(
            f"\nКуки сохранены в {state_file}\n"
            "Для работы на сервере скопируй файл и установи:\n"
            f"  BROWSER_HEADLESS=true\n"
            f"  BROWSER_STATE_FILE={state_file}"
        ))
