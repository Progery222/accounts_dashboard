"""
Импорт сессии Instagram для Playwright (instagram_state.json).

Usage:
    python manage.py setup_instagram_auth --from-chrome
    python manage.py setup_instagram_auth --cookie-file cookies.json

Воркер Instagram читает instagram_state.json, не instaloader .session.
"""
import base64
import json
import os
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from accounts.chromium_cookie_store import open_cookie_store


def _copy_locked_file(src: Path, dst: Path) -> Path:
    import win32con
    import win32file

    handle = win32file.CreateFile(
        str(src),
        win32con.GENERIC_READ,
        win32con.FILE_SHARE_READ | win32con.FILE_SHARE_WRITE | win32con.FILE_SHARE_DELETE,
        None,
        win32con.OPEN_EXISTING,
        win32con.FILE_ATTRIBUTE_NORMAL,
        None,
    )
    try:
        chunks = []
        while True:
            rc, chunk = win32file.ReadFile(handle, 1024 * 1024)
            if rc != 0 or not chunk:
                break
            chunks.append(chunk)
        dst.write_bytes(b"".join(chunks))
    finally:
        win32file.CloseHandle(handle)
    return dst


class Command(BaseCommand):
    help = "Импорт куков Instagram в instagram_state.json для Playwright worker"

    def add_arguments(self, parser):
        parser.add_argument(
            "--from-chrome",
            action="store_true",
            help="Импортировать куки Instagram из Chrome",
        )
        parser.add_argument(
            "--cookie-file",
            metavar="PATH",
            help="JSON с куками (EditThisCookie / Cookie-Editor)",
        )
        parser.add_argument(
            "--verify",
            metavar="USERNAME",
            default="freemarketsignal",
            help="Проверить сессию через counts_only worker (по умолчанию freemarketsignal)",
        )

    def handle(self, *args, **options):
        from platforms.instagram.session_state import write_instagram_storage_state
        from platforms.worker_utils import state_file_path

        state_path = state_file_path("instagram")

        if options["from_chrome"]:
            cookies = self._cookies_from_chrome()
        elif options["cookie_file"]:
            cookies = self._cookies_from_file(options["cookie_file"])
        else:
            raise CommandError(
                "Укажите --from-chrome или --cookie-file PATH\n"
                "Либо войдите через настройки дашборда (headed-авторизация Instagram)."
            )

        if "sessionid" not in cookies or not cookies.get("sessionid"):
            raise CommandError("Нет sessionid — войдите в Instagram в браузере и повторите.")

        write_instagram_storage_state(cookies, state_path)
        self.stdout.write(self.style.SUCCESS(f"Сохранено: {state_path} ({len(cookies)} куков)"))

        verify_user = (options.get("verify") or "").strip().lstrip("@")
        if verify_user:
            self._verify_playwright(verify_user)

    def _verify_playwright(self, username: str) -> None:
        from platforms.instagram.scraper import _call_instagram_worker

        self.stdout.write(f"Проверка Playwright @{username}…")
        try:
            data = _call_instagram_worker({"username": username, "counts_only": True})
        except Exception as exc:
            self.stdout.write(self.style.ERROR(f"Worker: {exc}"))
            return
        self.stdout.write(
            self.style.SUCCESS(
                f"OK followers={data.get('follower_count')} "
                f"following={data.get('following_count')} posts={data.get('post_count')}"
            )
        )

    def _cookies_from_file(self, cookie_file: str) -> dict[str, str]:
        try:
            raw = json.loads(Path(cookie_file).read_text(encoding="utf-8"))
        except Exception as exc:
            raise CommandError(f"Не удалось прочитать файл куков: {exc}") from exc

        if isinstance(raw, list):
            return {
                c["name"]: c["value"]
                for c in raw
                if isinstance(c, dict) and "name" in c and "value" in c
            }
        if isinstance(raw, dict):
            return {str(k): str(v) for k, v in raw.items()}
        raise CommandError("Неизвестный формат файла куков.")

    def _cookies_from_chrome(self) -> dict[str, str]:
        try:
            import win32crypt
        except ImportError as exc:
            raise CommandError("Установи pywin32: pip install pywin32") from exc
        try:
            from Crypto.Cipher import AES
        except ImportError as exc:
            raise CommandError("Установи pycryptodome: pip install pycryptodome") from exc

        chrome_dir = Path(os.environ["LOCALAPPDATA"]) / "Google" / "Chrome" / "User Data"
        if not chrome_dir.exists():
            raise CommandError(f"Папка Chrome не найдена: {chrome_dir}")

        local_state_path = chrome_dir / "Local State"
        try:
            local_state = json.loads(local_state_path.read_text(encoding="utf-8"))
            enc_key_b64 = local_state["os_crypt"]["encrypted_key"]
        except Exception as exc:
            raise CommandError(f"Не удалось прочитать Local State Chrome: {exc}") from exc

        enc_key = base64.b64decode(enc_key_b64)[5:]
        try:
            master_key = win32crypt.CryptUnprotectData(enc_key, None, None, None, 0)[1]
        except Exception as exc:
            raise CommandError(f"Не удалось расшифровать ключ Chrome (DPAPI): {exc}") from exc

        cookies_db = chrome_dir / "Default" / "Network" / "Cookies"
        if not cookies_db.exists():
            cookies_db = chrome_dir / "Default" / "Cookies"
        if not cookies_db.exists():
            raise CommandError("Файл куков Chrome не найден.")

        import shutil
        import tempfile

        tmp_dir = Path(tempfile.mkdtemp())
        tmp_db = tmp_dir / "cookies.db"
        try:
            shutil.copy2(str(cookies_db), str(tmp_db))
        except PermissionError:
            tmp_db = _copy_locked_file(cookies_db, tmp_db)

        try:
            con = open_cookie_store(tmp_db)
            rows = con.execute(
                "SELECT name, encrypted_value FROM cookies WHERE host_key LIKE '%instagram.com'"
            ).fetchall()
        except Exception as exc:
            raise CommandError(f"Не удалось прочитать куки Chrome: {exc}") from exc
        finally:
            con.close()

        if not rows:
            raise CommandError("Instagram куки в Chrome не найдены. Войдите в instagram.com в Chrome.")

        def _decrypt(enc_value: bytes) -> str:
            try:
                if enc_value[:3] == b"v10":
                    nonce = enc_value[3:15]
                    cipher_text = enc_value[15:]
                    cipher = AES.new(master_key, AES.MODE_GCM, nonce=nonce)
                    return cipher.decrypt_and_verify(cipher_text[:-16], cipher_text[-16:]).decode()
                return win32crypt.CryptUnprotectData(enc_value, None, None, None, 0)[1].decode()
            except Exception:
                return ""

        cookies = {name: _decrypt(enc_val) for name, enc_val in rows}
        return {k: v for k, v in cookies.items() if v}
