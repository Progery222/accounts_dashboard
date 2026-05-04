"""
One-time Telegram authorization.

Usage:
    python manage.py setup_telegram_auth

Requires TELEGRAM_API_ID, TELEGRAM_API_HASH, TELEGRAM_PHONE in .env.
After running, creates the session file at TELEGRAM_SESSION_FILE (default: telegram.session).
Copy the session file to the server — no re-auth needed after that.
"""
import asyncio
from django.core.management.base import BaseCommand, CommandError
from django.conf import settings


class Command(BaseCommand):
    help = "Авторизация в Telegram (выполняется один раз, создаёт файл сессии)"

    def handle(self, *args, **options):
        api_id = getattr(settings, "TELEGRAM_API_ID", None)
        api_hash = getattr(settings, "TELEGRAM_API_HASH", None)
        phone = getattr(settings, "TELEGRAM_PHONE", None)
        session_file = getattr(settings, "TELEGRAM_SESSION_FILE", "telegram.session")

        if not api_id or not api_hash:
            raise CommandError(
                "Укажи TELEGRAM_API_ID и TELEGRAM_API_HASH в .env\n"
                "Получить можно на https://my.telegram.org → API development tools"
            )
        if not phone:
            raise CommandError("Укажи TELEGRAM_PHONE в .env (например: +79001234567)")

        self.stdout.write(f"Авторизация в Telegram для {phone}...")
        self.stdout.write(f"Сессия будет сохранена в: {session_file}\n")

        asyncio.run(self._auth(int(api_id), api_hash, phone, session_file))

    async def _auth(self, api_id: int, api_hash: str, phone: str, session_file: str):
        from telethon import TelegramClient

        client = TelegramClient(session_file, api_id, api_hash)
        await client.connect()

        if await client.is_user_authorized():
            self.stdout.write(self.style.SUCCESS("Уже авторизован. Сессия актуальна."))
            await client.disconnect()
            return

        await client.send_code_request(phone)
        self.stdout.write(f"SMS-код отправлен на {phone}.")
        code = input("Введи код из SMS: ").strip()

        try:
            await client.sign_in(phone, code)
        except Exception as e:
            if "two-steps" in str(e).lower() or "password" in str(e).lower():
                password = input("Введи пароль двухфакторной аутентификации: ").strip()
                await client.sign_in(password=password)
            else:
                raise CommandError(f"Ошибка авторизации: {e}")

        await client.disconnect()
        self.stdout.write(self.style.SUCCESS(
            f"\nАвторизация успешна! Сессия сохранена в {session_file}.session\n"
            f"Скопируй этот файл на сервер и убедись, что TELEGRAM_SESSION_FILE указывает на него."
        ))
