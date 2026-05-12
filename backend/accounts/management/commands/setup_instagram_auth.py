"""
One-time Instagram authorization via instaloader.

Usage:
    python manage.py setup_instagram_auth              # login with username+password
    python manage.py setup_instagram_auth --from-chrome  # import cookies from Chrome (recommended)

The --from-chrome flag reads Instagram cookies directly from your Chrome profile.
Chrome can be open. No admin rights needed. No username/password required.

After running, all Instagram scraping uses the saved session — no browser needed.
"""
import base64
import json
import os
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from accounts.chromium_cookie_store import open_cookie_store


def _copy_locked_file(src: Path, dst: Path) -> Path:
    """
    Copy a file locked by another process (e.g. Chrome's Cookies DB) using
    win32file with FILE_SHARE_READ|WRITE|DELETE so Chrome's lock is bypassed.
    """
    import win32file
    import win32con

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
            rc, chunk = win32file.ReadFile(handle, 1024 * 1024)  # 1 MB at a time
            if rc != 0 or not chunk:
                break
            chunks.append(chunk)
        dst.write_bytes(b"".join(chunks))
    finally:
        win32file.CloseHandle(handle)

    return dst


class Command(BaseCommand):
    help = "Авторизация в Instagram через instaloader (выполняется один раз, создаёт файл сессии)"

    def add_arguments(self, parser):
        parser.add_argument(
            "--from-chrome",
            action="store_true",
            help="Импортировать куки Instagram из Chrome (закрой Chrome перед запуском)",
        )
        parser.add_argument(
            "--cookie-file",
            metavar="PATH",
            help="JSON-файл с куками из расширения браузера (EditThisCookie / Cookie-Editor)",
        )

    def handle(self, *args, **options):
        session_file = getattr(settings, "INSTAGRAM_SESSION_FILE", "instagram.session")

        if options["from_chrome"]:
            self.stdout.write("Импортирую куки Instagram из Chrome…")
            self.stdout.write(self.style.WARNING(
                "Убедись, что Chrome ЗАКРЫТ — иначе файл куков заблокирован."
            ))
            self._import_from_chrome(session_file)
            return

        if options["cookie_file"]:
            self.stdout.write(f"Импортирую куки из файла: {options['cookie_file']}…")
            self._import_from_cookie_file(options["cookie_file"], session_file)
            return

        # ── username/password login ──────────────────────────────────────────
        username = getattr(settings, "INSTAGRAM_USERNAME", "")
        password = getattr(settings, "INSTAGRAM_PASSWORD", "")

        if not username or not password:
            raise CommandError(
                "Укажи INSTAGRAM_USERNAME и INSTAGRAM_PASSWORD в .env\n"
                "Или используй: python manage.py setup_instagram_auth --from-chrome"
            )

        self.stdout.write(f"Авторизация в Instagram для @{username}…")
        self.stdout.write(f"Сессия будет сохранена в: {session_file}\n")

        try:
            import instaloader
        except ImportError:
            raise CommandError("Установи instaloader: pip install instaloader")

        L = instaloader.Instaloader(
            download_pictures=False,
            download_videos=False,
            download_video_thumbnails=False,
            compress_json=False,
            save_metadata=False,
            quiet=False,
        )

        session_path = Path(session_file)

        # Check if session already works
        if session_path.exists():
            try:
                L.load_session_from_file(username, str(session_path))
                profile = instaloader.Profile.from_username(L.context, username)
                self.stdout.write(self.style.SUCCESS(
                    f"Сессия актуальна. Профиль: {profile.full_name} "
                    f"({profile.followers} подписчиков)"
                ))
                return
            except Exception:
                self.stdout.write("Сохранённая сессия устарела, выполняю вход заново…")

        # Fresh login
        try:
            L.login(username, password)
        except instaloader.exceptions.BadCredentialsException:
            raise CommandError("Неверный логин или пароль Instagram.")
        except instaloader.exceptions.TwoFactorAuthRequiredException:
            code = input("Введи код двухфакторной аутентификации Instagram: ").strip()
            try:
                L.two_factor_login(code)
            except Exception as e:
                raise CommandError(f"Ошибка 2FA: {e}")
        except instaloader.exceptions.ConnectionException as e:
            msg = str(e).lower()
            if "checkpoint" in msg or "challenge" in msg or "verify" in msg:
                self.stdout.write(self.style.WARNING(
                    "\nInstagram требует подтверждение личности.\n"
                    "Открой Instagram в браузере, подтверди вход (письмо / SMS),\n"
                    "затем нажми Enter здесь чтобы повторить попытку."
                ))
                input()
                try:
                    L.login(username, password)
                except Exception as e2:
                    raise CommandError(f"Повторный вход не удался: {e2}")
            else:
                raise CommandError(f"Ошибка подключения: {e}")
        except Exception as e:
            raise CommandError(
                f"Ошибка входа: {e}\n"
                "Попробуй импорт из Chrome: python manage.py setup_instagram_auth --from-chrome"
            )

        session_path.parent.mkdir(parents=True, exist_ok=True)
        L.save_session_to_file(str(session_path))
        self.stdout.write(self.style.SUCCESS(
            f"\nАвторизация успешна! Сессия сохранена в {session_file}"
        ))

    # ── JSON cookie file import ──────────────────────────────────────────────

    def _import_from_cookie_file(self, cookie_file: str, session_file: str):
        """
        Import Instagram session from a JSON cookie export.

        Supported formats:
        - EditThisCookie / Cookie-Editor array format:
          [{"name": "sessionid", "value": "...", "domain": ".instagram.com", ...}, ...]
        - Simple dict format: {"sessionid": "...", "csrftoken": "...", ...}
        """
        try:
            import instaloader
        except ImportError:
            raise CommandError("Установи instaloader: pip install instaloader")

        try:
            raw = json.loads(Path(cookie_file).read_text(encoding="utf-8"))
        except Exception as e:
            raise CommandError(f"Не удалось прочитать файл куков: {e}")

        # Normalise to dict
        if isinstance(raw, list):
            cookies = {c["name"]: c["value"] for c in raw if "name" in c and "value" in c}
        elif isinstance(raw, dict):
            cookies = raw
        else:
            raise CommandError("Неизвестный формат файла куков.")

        ig_keys = {"sessionid", "csrftoken", "ds_user_id", "mid", "ig_did"}
        found = ig_keys & set(cookies)
        if not found:
            raise CommandError(
                f"Файл не содержит Instagram куков (нет ни одного из: {ig_keys}).\n"
                "Убедись, что экспортировал куки с сайта instagram.com."
            )

        self.stdout.write(f"Найдены куки: {', '.join(sorted(found))}")

        L = instaloader.Instaloader(
            download_pictures=False, download_videos=False,
            compress_json=False, save_metadata=False, quiet=True,
        )
        session = L.context._session
        for name, value in cookies.items():
            session.cookies.set(name, value, domain=".instagram.com")

        # Verify
        username_setting = getattr(settings, "INSTAGRAM_USERNAME", "")
        test_user = username_setting or "instagram"
        try:
            profile = instaloader.Profile.from_username(L.context, test_user)
            self.stdout.write(f"Сессия работает. Профиль @{test_user}: {profile.full_name}")
        except Exception as e:
            self.stdout.write(self.style.WARNING(f"Проверка сессии: {e} — сохраняю всё равно."))

        session_path = Path(session_file)
        session_path.parent.mkdir(parents=True, exist_ok=True)
        if username_setting:
            L.context.username = username_setting  # required by save_session_to_file
            L.save_session_to_file(str(session_path))
        else:
            import pickle
            session_path.write_bytes(pickle.dumps(session.cookies))

        self.stdout.write(self.style.SUCCESS(
            f"\nСессия сохранена в {session_file}\n"
            "Теперь обновление Instagram аккаунтов работает без браузера."
        ))

    # ── Chrome cookie import ─────────────────────────────────────────────────

    def _import_from_chrome(self, session_file: str):
        """
        Read Instagram cookies directly from Chrome's cookie database.
        Uses AES-256-GCM decryption (Chrome v80+). Chrome can be open.
        """
        try:
            import win32crypt
        except ImportError:
            raise CommandError("Установи pywin32: pip install pywin32")
        try:
            from Crypto.Cipher import AES
        except ImportError:
            raise CommandError("Установи pycryptodome: pip install pycryptodome")
        try:
            import instaloader
        except ImportError:
            raise CommandError("Установи instaloader: pip install instaloader")

        chrome_dir = Path(os.environ["LOCALAPPDATA"]) / "Google" / "Chrome" / "User Data"
        if not chrome_dir.exists():
            raise CommandError(f"Папка Chrome не найдена: {chrome_dir}")

        # 1. Read master AES key (DPAPI-encrypted, stored in Local State)
        local_state_path = chrome_dir / "Local State"
        try:
            local_state = json.loads(local_state_path.read_text(encoding="utf-8"))
            enc_key_b64 = local_state["os_crypt"]["encrypted_key"]
        except Exception as e:
            raise CommandError(f"Не удалось прочитать Local State Chrome: {e}")

        enc_key = base64.b64decode(enc_key_b64)[5:]  # strip "DPAPI" prefix
        try:
            master_key = win32crypt.CryptUnprotectData(enc_key, None, None, None, 0)[1]
        except Exception as e:
            raise CommandError(f"Не удалось расшифровать ключ Chrome (DPAPI): {e}")

        # 2. Open cookie DB (immutable=1 → works even when Chrome is running)
        cookies_db = chrome_dir / "Default" / "Network" / "Cookies"
        if not cookies_db.exists():
            cookies_db = chrome_dir / "Default" / "Cookies"
        if not cookies_db.exists():
            raise CommandError("Файл куков Chrome не найден.")

        # Копия файла во временный каталог (путь с пробелами надёжнее, чем URI).
        import shutil, tempfile
        tmp_dir = Path(tempfile.mkdtemp())
        tmp_db = tmp_dir / "cookies.db"
        try:
            shutil.copy2(str(cookies_db), str(tmp_db))
        except PermissionError:
            # Chrome is running and has the file locked — use ctypes ReadFile with shared access
            tmp_db = _copy_locked_file(cookies_db, tmp_db)

        try:
            con = open_cookie_store(tmp_db)
        except Exception as e:
            raise CommandError(f"Не удалось открыть БД куков Chrome: {e}")

        # 3. Extract Instagram cookies
        try:
            rows = con.execute(
                "SELECT name, encrypted_value FROM cookies "
                "WHERE host_key LIKE '%instagram.com'"
            ).fetchall()
        except Exception as e:
            raise CommandError(f"Ошибка чтения куков: {e}")
        finally:
            con.close()

        if not rows:
            raise CommandError(
                "Instagram куки в Chrome не найдены.\n"
                "Убедись, что ты вошёл в Instagram в Chrome."
            )

        # 4. Decrypt each cookie value
        def _decrypt(enc_value: bytes) -> str:
            try:
                if enc_value[:3] == b"v10":
                    # AES-256-GCM (Chrome v80+)
                    nonce = enc_value[3:15]
                    cipher_text = enc_value[15:]
                    cipher = AES.new(master_key, AES.MODE_GCM, nonce=nonce)
                    return cipher.decrypt_and_verify(cipher_text[:-16], cipher_text[-16:]).decode()
                else:
                    # Old DPAPI per-cookie encryption
                    return win32crypt.CryptUnprotectData(enc_value, None, None, None, 0)[1].decode()
            except Exception:
                return ""

        cookies = {name: _decrypt(enc_val) for name, enc_val in rows}
        cookies = {k: v for k, v in cookies.items() if v}

        self.stdout.write(f"Найдено {len(cookies)} Instagram куков в Chrome.")

        # 5. Inject cookies into instaloader session
        L = instaloader.Instaloader(
            download_pictures=False,
            download_videos=False,
            compress_json=False,
            save_metadata=False,
            quiet=True,
        )
        session = L.context._session
        for name, value in cookies.items():
            session.cookies.set(name, value, domain=".instagram.com")

        # 6. Verify session works
        username_setting = getattr(settings, "INSTAGRAM_USERNAME", "")
        try:
            test_user = username_setting or "instagram"
            profile = instaloader.Profile.from_username(L.context, test_user)
            self.stdout.write(
                f"Сессия работает. Профиль @{test_user}: {profile.full_name}"
            )
        except Exception as e:
            self.stdout.write(self.style.WARNING(
                f"Предупреждение при проверке сессии: {e}\n"
                "Сессия всё равно будет сохранена."
            ))

        # 7. Save session file
        session_path = Path(session_file)
        session_path.parent.mkdir(parents=True, exist_ok=True)
        if username_setting:
            L.save_session_to_file(str(session_path))
        else:
            # save_session_to_file needs a username — save raw cookies instead
            import pickle
            with open(session_path, "wb") as f:
                pickle.dump(session.cookies, f)

        self.stdout.write(self.style.SUCCESS(
            f"\nСессия сохранена в {session_file}\n"
            "Теперь обновление Instagram аккаунтов работает без браузера."
        ))
