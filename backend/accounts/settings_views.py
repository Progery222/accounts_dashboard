"""
Settings API — authentication management for social platforms.

Endpoints (фрагмент):
  GET  /api/settings/status/                     — статус авторизации по платформам
  POST /api/settings/<platform>/logout/          — сброс сессии (куки/state/IndexedDB)
  POST /api/settings/<platform>/start-auth/      — браузерный вход
  GET  /api/settings/job/<job_id>/               — прогресс фоновой задачи
"""
import asyncio
import os
import shutil
import sys
import subprocess
import tempfile
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework import status as drf_status

from .models import Account
from .chromium_cookie_store import open_cookie_store

# ── Job registry ──────────────────────────────────────────────────────────────
# {job_id: {"status": "pending"|"done"|"error", "message": str}}
_jobs: dict[str, dict] = {}
_jobs_lock = threading.Lock()

EPOCH_DIFF = 11644473600  # seconds between Windows epoch (1601) and Unix epoch (1970)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _default_profile_dir() -> str:
    home = Path.home()
    if (home / "AppData").exists():  # Windows
        return str(home / "AppData" / "Local" / "TikStatsChromeProfile")
    return str(home / ".config" / "tikstats-chrome-profile")


def _cleanup_chrome_artifacts(profile_dir: str) -> None:
    """Delete stale .CHROME_DELETE / Snapshots artefacts that prevent Chrome from starting."""
    base = Path(profile_dir)
    if not base.exists():
        return
    for entry in base.iterdir():
        if entry.name.endswith(".CHROME_DELETE") or entry.name == "Snapshots":
            try:
                shutil.rmtree(entry, ignore_errors=True)
            except Exception:
                pass


def _get_profile_dir() -> str:
    """Каталог профиля Chromium (как у Playwright-воркеров)."""
    try:
        from django.conf import settings as dj_settings
        prof = getattr(dj_settings, "ACCOUNTS_BROWSER_PROFILE_DIR", None)
        if prof:
            return str(prof)
    except Exception:
        pass
    raw = (os.environ.get("BROWSER_PROFILE_DIR") or "").strip()
    if raw:
        return raw
    return _default_profile_dir()


def _get_setting(name: str, default: str = "") -> str:
    try:
        from django.conf import settings
        return getattr(settings, name, default) or default
    except Exception:
        return default


def _read_tiktok_cookies() -> list[dict]:
    """Read TikTok cookie expiry dates from the persistent Chrome profile."""
    profile_dir = _get_profile_dir()
    db_path = Path(profile_dir) / "Default" / "Network" / "Cookies"
    if not db_path.exists():
        return []
    tmp = tempfile.mktemp(suffix=".db")
    try:
        shutil.copy2(str(db_path), tmp)
        conn = open_cookie_store(tmp)
        cur = conn.cursor()
        cur.execute("""
            SELECT host_key, name, expires_utc
            FROM cookies
            WHERE host_key LIKE '%tiktok%'
            ORDER BY expires_utc
        """)
        rows = cur.fetchall()
        conn.close()
    except Exception:
        return []
    finally:
        try:
            os.unlink(tmp)
        except Exception:
            pass

    result = []
    for host, name, exp_us in rows:
        if exp_us == 0:
            expires_iso = None
            expires_ts = None
        else:
            exp_sec = exp_us / 1_000_000 - EPOCH_DIFF
            try:
                dt = datetime.fromtimestamp(exp_sec, tz=timezone.utc)
                expires_iso = dt.strftime("%Y-%m-%d %H:%M UTC")
                expires_ts = exp_sec
            except Exception:
                expires_iso = None
                expires_ts = None
        result.append({"host": host, "name": name, "expires": expires_iso, "expires_ts": expires_ts})
    return result


def _tiktok_has_session() -> bool:
    """Return True if TikTok auth session cookie exists in profile."""
    profile_dir = _get_profile_dir()
    db_path = Path(profile_dir) / "Default" / "Network" / "Cookies"
    if db_path.exists():
        tmp = tempfile.mktemp(suffix=".db")
        try:
            shutil.copy2(str(db_path), tmp)
            conn = open_cookie_store(tmp)
            cur = conn.cursor()
            cur.execute("""
                SELECT name FROM cookies
                WHERE host_key LIKE '%tiktok%'
                  AND (name = 'sessionid' OR name = 'sessionid_ss')
                LIMIT 1
            """)
            row = cur.fetchone()
            conn.close()
            if row is not None:
                return True
        except Exception:
            pass
        finally:
            try:
                os.unlink(tmp)
            except Exception:
                pass
    # Fallback: when Chromium profile cookie DB is missing/unreadable, accept
    # session from exported Playwright state file.
    try:
        state_path = Path(profile_dir) / "tiktok_state.json"
        if state_path.exists():
            data = _json.loads(state_path.read_text(encoding="utf-8"))
            cookies = data.get("cookies") if isinstance(data, dict) else []
            if isinstance(cookies, list):
                for c in cookies:
                    if not isinstance(c, dict):
                        continue
                    name = str(c.get("name", ""))
                    domain = str(c.get("domain", "")).lower()
                    if name in {"sessionid", "sessionid_ss"} and "tiktok" in domain:
                        return True
    except Exception:
        pass
    return False


# ── Status endpoints ──────────────────────────────────────────────────────────

def _tiktok_status() -> dict:
    cookies = _read_tiktok_cookies()
    has_session = _tiktok_has_session()  # requires sessionid cookie
    if not cookies:
        return {"has_session": has_session, "cookies": [], "min_expires": None, "min_expires_name": None}

    with_expiry = [(c["expires_ts"], c["expires"], c["name"]) for c in cookies if c["expires_ts"]]
    if with_expiry:
        _, exp_str, name = min(with_expiry, key=lambda x: x[0])
    else:
        exp_str, name = None, None

    return {
        "has_session": has_session,
        "cookies": cookies,
        "min_expires": exp_str,
        "min_expires_name": name,
    }


def _x_status() -> dict:
    return {"has_session": _check_cookie_in_profile(["twitter.com", ".x.com"], ["auth_token"])}


def _threads_status() -> dict:
    return {"has_session": _check_cookie_in_profile(["threads.net", "threads.com"], ["sessionid"])}


def _telegram_status() -> dict:
    """Check whether a web.telegram.org session exists in the Chrome profile."""
    profile_dir = Path(_get_profile_dir())
    indexed_db_dir = profile_dir / "Default" / "IndexedDB"

    has_session = False
    if indexed_db_dir.exists():
        for item in indexed_db_dir.iterdir():
            name_lower = item.name.lower()
            if "telegram.org" in name_lower or "web.telegram" in name_lower:
                has_session = True
                break

    return {
        "has_session": has_session,
        "profile_exists": profile_dir.exists(),
    }


def _instagram_status() -> dict:
    username = _get_setting("INSTAGRAM_USERNAME", "")
    session_file = _get_setting("INSTAGRAM_SESSION_FILE", "instagram.session")
    session_path = Path(session_file)
    if not session_path.is_absolute():
        session_path = Path(__file__).parent.parent / session_path
    if session_path.exists():
        mtime = datetime.fromtimestamp(session_path.stat().st_mtime, tz=timezone.utc)
        return {
            "has_session": True,
            "username": username,
            "last_updated": mtime.strftime("%Y-%m-%d %H:%M UTC"),
        }
    ig_state = Path(_get_profile_dir()) / "instagram_state.json"
    if ig_state.exists():
        mtime = datetime.fromtimestamp(ig_state.stat().st_mtime, tz=timezone.utc)
        return {
            "has_session": _check_cookie_in_profile(["instagram.com"], ["sessionid"]),
            "username": username,
            "last_updated": mtime.strftime("%Y-%m-%d %H:%M UTC"),
        }
    has = _check_cookie_in_profile(["instagram.com"], ["sessionid"])
    return {"has_session": has, "username": username, "last_updated": None}


def _facebook_has_session() -> bool:
    """Return True if both c_user and xs cookies exist for facebook.com."""
    return _check_cookie_in_profile(["facebook.com"], ["c_user"])


def _facebook_status() -> dict:
    return {"has_session": _facebook_has_session()}


def _check_any_cookie_in_profile(domain_patterns: list[str]) -> bool:
    """Return True if any cookie exists for any of domain_patterns in the Chrome profile."""
    db_path = Path(_get_profile_dir()) / "Default" / "Network" / "Cookies"
    if not db_path.exists():
        return False
    tmp = tempfile.mktemp(suffix=".db")
    try:
        shutil.copy2(str(db_path), tmp)
        conn = open_cookie_store(tmp)
        cur = conn.cursor()
        domain_sql = " OR ".join(["host_key LIKE ?" for _ in domain_patterns])
        params = [f"%{p}%" for p in domain_patterns]
        cur.execute(f"SELECT name FROM cookies WHERE ({domain_sql}) LIMIT 1", params)
        row = cur.fetchone()
        conn.close()
        return row is not None
    except Exception:
        return False
    finally:
        try:
            os.unlink(tmp)
        except Exception:
            pass


def _rumble_has_session() -> bool:
    # Rumble auth/challenge cookies vary; treat any rumble.com cookie as active session footprint.
    return _check_any_cookie_in_profile(["rumble.com"])


def _rumble_status() -> dict:
    return {"has_session": _rumble_has_session()}


def _reddit_has_session() -> bool:
    # Reddit web auth footprint in Chromium profile.
    return _check_cookie_in_profile(["reddit.com"], ["reddit_session"])


def _reddit_status() -> dict:
    return {"has_session": _reddit_has_session()}


def _auth_status_payload() -> dict:
    return {
        "tiktok": _tiktok_status(),
        "instagram": _instagram_status(),
        "telegram": _telegram_status(),
        "x": _x_status(),
        "threads": _threads_status(),
        "facebook": _facebook_status(),
        "rumble": _rumble_status(),
        "reddit": _reddit_status(),
    }


@api_view(["GET"])
def auth_status(request):
    return Response(_auth_status_payload())


_LOGOUT_COOKIE_HOST_NEEDLES: dict[str, list[str]] = {
    "tiktok":    ["tiktok"],
    "instagram": ["instagram"],
    "telegram":  ["web.telegram.org", "telegram.org"],
    "x":         ["twitter.com", "x.com"],
    "threads":   ["threads.net", "threads.com"],
    "facebook":  ["facebook.com", "m.facebook.com", "fb.com"],
    "rumble":    ["rumble.com"],
    "reddit":    ["reddit.com"],
}


def _instagram_session_path() -> Path:
    session_file = _get_setting("INSTAGRAM_SESSION_FILE", "instagram.session")
    session_path = Path(session_file)
    if not session_path.is_absolute():
        session_path = Path(__file__).resolve().parent.parent / session_path
    return session_path


def _unlink_if_exists(path: Path) -> None:
    try:
        if path.is_file():
            path.unlink()
    except Exception:
        pass


def _delete_chrome_cookies_by_host_needles(needles: list[str]) -> None:
    """Удалить куки из профиля Chromium по подстрокам host_key (регистронезависимо)."""
    if not needles:
        return
    profile_dir = Path(_get_profile_dir())
    db_path = profile_dir / "Default" / "Network" / "Cookies"
    if not db_path.exists():
        return
    tmp_fd, tmp_path = tempfile.mkstemp(suffix=".db")
    os.close(tmp_fd)
    try:
        shutil.copy2(db_path, tmp_path)
        conn = open_cookie_store(tmp_path)
        where = " OR ".join(["lower(host_key) LIKE ?" for _ in needles])
        params = [f"%{n.lower()}%" for n in needles]
        conn.execute(f"DELETE FROM cookies WHERE {where}", params)
        conn.commit()
        conn.close()
        os.replace(tmp_path, str(db_path))
    except Exception:
        try:
            os.unlink(tmp_path)
        except Exception:
            pass
        raise


def _clear_telegram_indexeddb() -> None:
    indexed_db_dir = Path(_get_profile_dir()) / "Default" / "IndexedDB"
    if not indexed_db_dir.is_dir():
        return
    for item in list(indexed_db_dir.iterdir()):
        if not item.is_dir():
            continue
        name_lower = item.name.lower()
        if "telegram.org" in name_lower or "web.telegram" in name_lower:
            shutil.rmtree(item, ignore_errors=True)


def _logout_platform(platform: str) -> None:
    profile = Path(_get_profile_dir())
    state_json = profile / f"{platform}_state.json"
    _unlink_if_exists(state_json)

    if platform == "instagram":
        session_file = _get_setting("INSTAGRAM_SESSION_FILE", "instagram.session")
        session_path = Path(session_file)
        if not session_path.is_absolute():
            session_path = Path(__file__).parent.parent / session_path
        _unlink_if_exists(session_path)

    if platform == "telegram":
        _clear_telegram_indexeddb()

    needles = _LOGOUT_COOKIE_HOST_NEEDLES.get(platform, [])
    if needles:
        _delete_chrome_cookies_by_host_needles(needles)

    try:
        from platforms.worker_pool import shutdown_all_workers

        shutdown_all_workers()
    except Exception:
        pass


_LOGOUT_ALLOWED = frozenset(_LOGOUT_COOKIE_HOST_NEEDLES.keys())


@api_view(["POST"])
def auth_logout(request, platform: str):
    """Сбросить сохранённую сессию платформы (куки профиля, state JSON, при необходимости IndexedDB)."""
    p = (platform or "").strip().lower()
    if p not in _LOGOUT_ALLOWED:
        return Response({"detail": "Неизвестная платформа."}, status=drf_status.HTTP_404_NOT_FOUND)
    try:
        _logout_platform(p)
    except PermissionError as e:
        return Response(
            {"detail": f"Не удалось записать файл куков (возможно, профиль занят браузером): {e}"},
            status=drf_status.HTTP_409_CONFLICT,
        )
    except OSError as e:
        win_busy = getattr(e, "winerror", None) == 32
        if win_busy:
            return Response(
                {"detail": "Профиль браузера занят другим процессом. Закройте окна входа и повторите."},
                status=drf_status.HTTP_409_CONFLICT,
            )
        return Response({"detail": str(e)}, status=drf_status.HTTP_500_INTERNAL_SERVER_ERROR)
    except Exception as e:
        return Response({"detail": str(e)}, status=drf_status.HTTP_500_INTERNAL_SERVER_ERROR)
    return Response({"ok": True, "detail": "Сессия сброшена."})


# ── Generic job helpers ───────────────────────────────────────────────────────

def _set_job(job_id: str, status: str, message: str) -> None:
    with _jobs_lock:
        _jobs[job_id] = {"status": status, "message": message}


def _new_job() -> str:
    job_id = str(uuid.uuid4())
    with _jobs_lock:
        _jobs[job_id] = {"status": "pending", "message": "Запуск…"}
    return job_id


@api_view(["GET"])
def job_status(request, job_id: str):
    with _jobs_lock:
        job = _jobs.get(job_id)
    if not job:
        return Response({"detail": "Задача не найдена."}, status=drf_status.HTTP_404_NOT_FOUND)
    return Response(job)


# ── TikTok browser auth ───────────────────────────────────────────────────────

def _start_xvfb_if_needed() -> subprocess.Popen | None:
    """
    Start Xvfb only for Linux server environments when there is no active DISPLAY.
    Returns process handle if started by this function, otherwise None.
    """
    # Local desktop flows (Windows/macOS) should open a normal browser window
    # and must not require Xvfb.
    if os.name == "nt" or os.uname().sysname.lower() == "darwin":
        return None

    display = os.environ.get("DISPLAY") or _get_setting("BROWSER_DISPLAY", ":99")
    disp_num = display.lstrip(":").split(".")[0]
    x11_socket = Path("/tmp/.X11-unix") / f"X{disp_num}"
    if x11_socket.exists():
        return None

    cmd = ["Xvfb", display, "-screen", "0", "1366x768x24", "-nolisten", "tcp", "-ac"]
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    # Give Xvfb a moment to initialize.
    time.sleep(0.8)
    if proc.poll() is not None:
        raise RuntimeError("Не удалось запустить Xvfb для браузерной авторизации.")
    os.environ["DISPLAY"] = display
    return proc


def _release_chrome_profile_lock(profile_dir: str) -> None:
    """Best-effort release of Chromium profile locks before headed auth."""
    base = Path(profile_dir)
    for name in ("SingletonLock", "SingletonCookie", "SingletonSocket"):
        p = base / name
        try:
            if p.exists() or p.is_symlink():
                p.unlink()
        except Exception:
            pass

    try:
        from platforms.worker_utils import kill_chrome_processes_for_profile

        kill_chrome_processes_for_profile(profile_dir)
    except Exception:
        pass


def _prepare_browser_for_headed_auth(job_id: str | None = None) -> str:
    """
    Перед окном входа: остановить фоновые Playwright-воркеры (они держат профиль)
    и снять lock Chromium.
    """
    profile_dir = _get_profile_dir()
    if job_id:
        _set_job(
            job_id,
            "pending",
            "Останавливаю фоновые воркеры и открываю окно браузера…",
        )
    try:
        from platforms.worker_pool import shutdown_all_workers

        shutdown_all_workers()
    except Exception:
        pass
    time.sleep(0.4)
    _release_chrome_profile_lock(profile_dir)
    return profile_dir


def _auth_nav_timeout_ms() -> int:
    raw = os.environ.get("AUTH_NAV_TIMEOUT_MS")
    if raw is None or not str(raw).strip():
        return 45_000
    try:
        return max(15_000, min(120_000, int(str(raw).strip())))
    except ValueError:
        return 45_000


def _format_headed_browser_error(exc: Exception) -> str:
    msg = str(exc).replace("\r\n", " ").replace("\n", " ").strip()
    low = msg.lower()
    if "target page" in low or "has been closed" in low:
        return (
            f"{msg}. Возможно, профиль браузера занят — закройте другие окна Chromium "
            "или дождитесь окончания автообновления и повторите."
        )
    if "process" in low and "exit" in low:
        return (
            f"{msg}. Не удалось запустить Chromium — проверьте Playwright "
            "(python -m playwright install chromium) и что профиль не заблокирован."
        )
    if "timeout" in low and "exceeded" in low:
        return f"{msg}. Проверьте интернет и повторите; при медленной сети увеличьте AUTH_NAV_TIMEOUT_MS."
    return msg


async def _launch_persistent_context(
    pw,
    profile_dir: str,
    *,
    headless: bool = False,
    locale: str = "ru-RU",
):
    """Запуск Chromium с профилем; повтор при артефактах lock/CHROME_DELETE."""
    Path(profile_dir).mkdir(parents=True, exist_ok=True)
    last_exc: Exception | None = None
    kwargs: dict = {
        "headless": headless,
        "args": ["--disable-blink-features=AutomationControlled"],
        "locale": locale,
    }
    if not headless:
        kwargs["viewport"] = {"width": 1280, "height": 900}
    for attempt in range(2):
        try:
            return await pw.chromium.launch_persistent_context(profile_dir, **kwargs)
        except Exception as exc:
            last_exc = exc
            if attempt == 0:
                _cleanup_chrome_artifacts(profile_dir)
                await asyncio.sleep(0.8)
    assert last_exc is not None
    raise last_exc


def _run_tiktok_auth(job_id: str) -> None:
    profile_dir = _prepare_browser_for_headed_auth(job_id)
    username = _get_setting("TIKTOK_USERNAME")
    password = _get_setting("TIKTOK_PASSWORD")
    # По умолчанию: автозаполнение, если в .env заданы и логин, и пароль.
    # TIKTOK_AUTH_AUTOFILL=false — никогда не подставлять; true — подставлять при наличии пары.
    raw_af = (_get_setting("TIKTOK_AUTH_AUTOFILL", "") or "").strip().lower()
    if raw_af in {"0", "false", "no", "off", "n"}:
        autofill_enabled = False
    elif raw_af in {"1", "true", "yes", "on", "y"}:
        autofill_enabled = True
    else:
        autofill_enabled = bool(username and password)

    async def _async():
        from playwright.async_api import async_playwright

        from platforms.tiktok.auth_browser import try_fill_tiktok_login_credentials

        _set_job(job_id, "pending", "Запускаю браузер…")
        Path(profile_dir).mkdir(parents=True, exist_ok=True)
        xvfb_proc = None

        try:
            xvfb_proc = _start_xvfb_if_needed()
            if xvfb_proc is not None:
                _set_job(job_id, "pending", "Запущен Xvfb, открываю TikTok…")

            async with async_playwright() as pw:
                ctx = await _launch_persistent_context(
                    pw, profile_dir, headless=False, locale="en-US",
                )
                try:
                    page = ctx.pages[0] if ctx.pages else await ctx.new_page()

                    _set_job(job_id, "pending", "Открываю TikTok…")
                    if autofill_enabled and username and password:
                        ok = await try_fill_tiktok_login_credentials(page, username, password)
                        if ok:
                            _set_job(
                                job_id,
                                "pending",
                                "Логин и пароль подставлены — завершите вход (капча/2FA при необходимости)…",
                            )
                        else:
                            print(
                                "[tiktok_auth] автозаполнение не удалось — введите логин и пароль вручную.",
                                file=sys.stderr,
                            )
                            try:
                                await page.goto(
                                    "https://www.tiktok.com/login",
                                    wait_until="domcontentloaded",
                                    timeout=_auth_nav_timeout_ms(),
                                )
                                await page.wait_for_timeout(1500)
                            except Exception:
                                pass
                            _set_job(
                                job_id,
                                "pending",
                                "Войдите в TikTok в открытом окне браузера (автоподстановка не сработала)…",
                            )
                    else:
                        await page.goto(
                            "https://www.tiktok.com/login",
                            wait_until="domcontentloaded",
                            timeout=_auth_nav_timeout_ms(),
                        )
                        await page.wait_for_timeout(1500)
                        _set_job(
                            job_id,
                            "pending",
                            "Войдите в TikTok в открытом окне браузера (лучше через QR/2FA)…",
                        )

                    # Poll until sessionid cookie appears in the profile DB (up to 3 min)
                    for _ in range(180):
                        await asyncio.sleep(1)
                        if _tiktok_has_session():
                            break
                    else:
                        raise TimeoutError("Время ожидания входа истекло (3 мин).")

                    # Export state so the worker can use a non-persistent context
                    state_path = Path(profile_dir) / "tiktok_state.json"
                    await ctx.storage_state(path=str(state_path))
                    _set_job(job_id, "done", "Вход в TikTok выполнен успешно!")
                except Exception as e:
                    _set_job(job_id, "error", f"Ошибка: {_format_headed_browser_error(e)}")
                finally:
                    if ctx is not None:
                        await ctx.close()
        except FileNotFoundError:
            _set_job(job_id, "error", "Xvfb не установлен на сервере. Установите пакет xvfb.")
        except Exception as e:
            _set_job(job_id, "error", f"Ошибка: {_format_headed_browser_error(e)}")
        finally:
            if xvfb_proc is not None:
                xvfb_proc.terminate()
                try:
                    xvfb_proc.wait(timeout=5)
                except Exception:
                    xvfb_proc.kill()

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(_async())
    finally:
        loop.close()


@api_view(["POST"])
def tiktok_start_auth(request):
    job_id = _new_job()
    t = threading.Thread(target=_run_tiktok_auth, args=(job_id), daemon=True)
    t.start()
    return Response({"job_id": job_id})


# ── Generic cookie import helpers ────────────────────────────────────────────

import json as _json

_SAME_SITE_MAP = {
    "no_restriction": "None",
    "lax":            "Lax",
    "strict":         "Strict",
    "none":           "None",
    "unspecified":    "Lax",
}


def _parse_cookies_generic(
    raw: str,
    domain_contains: list[str],
    fallback_name: str,
    fallback_domain: str,
) -> list[dict]:
    """
    Parse raw cookie input (Cookie-Editor JSON or plain cookie value).
    domain_contains  — fragments that the cookie domain must contain (OR logic).
    fallback_name    — cookie name used when raw is a plain string value.
    fallback_domain  — domain used for the plain-value fallback cookie.
    """
    raw = raw.strip()
    try:
        data = _json.loads(raw)
    except _json.JSONDecodeError:
        data = None

    if data is None:
        # Plain string → treat as the primary session cookie value
        return [{
            "name":     fallback_name,
            "value":    raw,
            "domain":   fallback_domain,
            "path":     "/",
            "secure":   True,
            "httpOnly": True,
            "sameSite": "None",
        }]

    if not isinstance(data, list):
        raise ValueError("Ожидается JSON-массив куков или строка значения cookie")

    result = []
    for c in data:
        if not isinstance(c, dict):
            continue
        domain = c.get("domain", "")
        if not any(frag in domain for frag in domain_contains):
            continue
        pw: dict = {
            "name":   c.get("name", ""),
            "value":  c.get("value", ""),
            "domain": domain,
            "path":   c.get("path", "/"),
        }
        exp = c.get("expirationDate") or c.get("expires")
        if exp and isinstance(exp, (int, float)) and exp > 0:
            pw["expires"] = int(exp)
        if "httpOnly" in c:
            pw["httpOnly"] = bool(c["httpOnly"])
        if "secure" in c:
            pw["secure"] = bool(c["secure"])
        ss = str(c.get("sameSite", "")).lower()
        if ss in _SAME_SITE_MAP:
            pw["sameSite"] = _SAME_SITE_MAP[ss]
        result.append(pw)

    return result


def _check_cookie_in_profile(domain_patterns: list[str], cookie_names: list[str]) -> bool:
    """Return True if any of cookie_names exists for any of domain_patterns in the Chrome profile."""
    db_path = Path(_get_profile_dir()) / "Default" / "Network" / "Cookies"
    if not db_path.exists():
        return False
    tmp = tempfile.mktemp(suffix=".db")
    try:
        shutil.copy2(str(db_path), tmp)
        conn = open_cookie_store(tmp)
        cur = conn.cursor()
        domain_sql  = " OR ".join(["host_key LIKE ?" for _ in domain_patterns])
        name_sql    = " OR ".join(["name = ?"         for _ in cookie_names])
        params      = [f"%{p}%" for p in domain_patterns] + list(cookie_names)
        cur.execute(f"SELECT name FROM cookies WHERE ({domain_sql}) AND ({name_sql})", params)
        row = cur.fetchone()
        conn.close()
        return row is not None
    except Exception:
        return False
    finally:
        try:
            os.unlink(tmp)
        except Exception:
            pass


def _run_platform_cookie_import(
    job_id: str,
    pw_cookies: list[dict],
    has_session_fn,
    success_msg: str,
    fail_msg: str,
    post_import_fn=None,
    state_export_path: str | None = None,
) -> None:
    """
    Generic Playwright-based cookie import into the shared Chrome profile.

    state_export_path  — if set, the browser storage state is exported to this
                         JSON file *before* the context closes.  Workers then use
                         this file via a non-persistent context so the platform
                         cannot overwrite the profile's cookies during scraping.
    post_import_fn(ctx) is awaited before ctx.close() — use it for extra steps
    (e.g. saving an Instaloader session from the imported cookies).
    """
    profile_dir = _prepare_browser_for_headed_auth(job_id)

    async def _async():
        from playwright.async_api import async_playwright

        try:
            _set_job(job_id, "pending", "Открываю профиль браузера…")

            async with async_playwright() as pw:
                ctx = await _launch_persistent_context(pw, profile_dir, headless=True)
                try:
                    await ctx.add_cookies(pw_cookies)
                    _set_job(job_id, "pending", "Куки добавлены, сохраняю профиль…")
                    # Export per-platform state BEFORE post_import_fn / close so that
                    # workers can use an ephemeral context and the profile stays intact.
                    if state_export_path:
                        await ctx.storage_state(path=state_export_path)
                    if post_import_fn:
                        await post_import_fn(ctx)
                except Exception as e:
                    _set_job(job_id, "error", f"Ошибка добавления куков: {_format_headed_browser_error(e)}")
                    return
                finally:
                    if ctx is not None:
                        await ctx.close()

            if has_session_fn():
                _set_job(job_id, "done", success_msg)
            else:
                _set_job(job_id, "error", fail_msg)
        except Exception as e:
            _set_job(job_id, "error", f"Ошибка: {_format_headed_browser_error(e)}")

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(_async())
    finally:
        loop.close()


# ── TikTok cookie import ──────────────────────────────────────────────────────

@api_view(["POST"])
def tiktok_import_cookies(request):
    raw = (request.data.get("cookies") or "").strip()
    if not raw:
        return Response({"error": "Поле cookies обязательно"}, status=400)
    is_probably_json = raw.startswith("[")
    try:
        if is_probably_json:
            pw_cookies = _parse_cookies_generic(raw, ["tiktok"], "sessionid", ".tiktok.com")
        else:
            # Raw value fallback: try both commonly seen TikTok session cookie names.
            pw_cookies = [
                {
                    "name": "sessionid",
                    "value": raw,
                    "domain": ".tiktok.com",
                    "path": "/",
                    "secure": True,
                    "httpOnly": True,
                    "sameSite": "None",
                },
                {
                    "name": "sessionid_ss",
                    "value": raw,
                    "domain": ".tiktok.com",
                    "path": "/",
                    "secure": True,
                    "httpOnly": True,
                    "sameSite": "None",
                },
            ]
    except ValueError as e:
        return Response({"error": str(e)}, status=400)
    if not pw_cookies:
        return Response({"error": "Не найдено TikTok-куков (нужен домен .tiktok.com)"}, status=400)

    state_path = str(Path(_get_profile_dir()) / "tiktok_state.json")
    job_id = _new_job()
    t = threading.Thread(
        target=_run_platform_cookie_import,
        args=(
            job_id, pw_cookies, _tiktok_has_session,
            f"Готово! Импортировано {len(pw_cookies)} кук(ов). Авторизация TikTok активна.",
            "Не найдена TikTok-сессия после импорта (ожидались sessionid/sessionid_ss). "
            "Скопируйте куки с tiktok.com в залогиненном состоянии.",
        ),
        kwargs={"state_export_path": state_path},
        daemon=True,
    )
    t.start()
    return Response({"job_id": job_id})


# ── Instagram cookie import ───────────────────────────────────────────────────

def _instagram_has_session_chrome() -> bool:
    return _check_cookie_in_profile(["instagram.com"], ["sessionid"])


def _instagram_save_instaloader(pw_cookies: list[dict]) -> None:
    """Save imported Instagram cookies as an Instaloader .session file."""
    try:
        import instaloader
        session_file = _get_setting("INSTAGRAM_SESSION_FILE", "instagram.session")
        session_path = Path(session_file)
        if not session_path.is_absolute():
            session_path = Path(__file__).parent.parent / session_path
        username = _get_setting("INSTAGRAM_USERNAME", "") or "imported"

        L = instaloader.Instaloader()
        sess = L.context._session
        for c in pw_cookies:
            if "instagram.com" in c.get("domain", ""):
                sess.cookies.set(c["name"], c["value"], domain=".instagram.com")
        L.context.username = username
        L.save_session_to_file(str(session_path))
    except Exception:
        pass  # best-effort; Chrome profile cookies still work for Playwright worker


@api_view(["POST"])
def instagram_import_cookies(request):
    raw = (request.data.get("cookies") or "").strip()
    if not raw:
        return Response({"error": "Поле cookies обязательно"}, status=400)
    try:
        pw_cookies = _parse_cookies_generic(raw, ["instagram.com"], "sessionid", ".instagram.com")
    except ValueError as e:
        return Response({"error": str(e)}, status=400)
    if not pw_cookies:
        return Response({"error": "Не найдено Instagram-куков (нужен домен instagram.com)"}, status=400)

    async def _save_instaloader(ctx):
        _instagram_save_instaloader(pw_cookies)

    state_path = str(Path(_get_profile_dir()) / "instagram_state.json")
    job_id = _new_job()
    t = threading.Thread(
        target=_run_platform_cookie_import,
        args=(
            job_id, pw_cookies, _instagram_has_session_chrome,
            f"Готово! Импортировано {len(pw_cookies)} кук(ов). Авторизация Instagram активна.",
            "sessionid не найден после импорта. Скопируйте куки с instagram.com в залогиненном состоянии.",
            _save_instaloader,
        ),
        kwargs={"state_export_path": state_path},
        daemon=True,
    )
    t.start()
    return Response({"job_id": job_id})


# ── X (Twitter) cookie import ─────────────────────────────────────────────────

def _x_has_session() -> bool:
    return _check_cookie_in_profile(["twitter.com", ".x.com"], ["auth_token"])


@api_view(["POST"])
def x_import_cookies(request):
    raw = (request.data.get("cookies") or "").strip()
    if not raw:
        return Response({"error": "Поле cookies обязательно"}, status=400)
    try:
        pw_cookies = _parse_cookies_generic(raw, ["twitter.com", "x.com"], "auth_token", ".twitter.com")
    except ValueError as e:
        return Response({"error": str(e)}, status=400)
    if not pw_cookies:
        return Response({"error": "Не найдено X-куков (нужен домен twitter.com или x.com)"}, status=400)

    state_path = str(Path(_get_profile_dir()) / "x_state.json")
    job_id = _new_job()
    t = threading.Thread(
        target=_run_platform_cookie_import,
        args=(
            job_id, pw_cookies, _x_has_session,
            f"Готово! Импортировано {len(pw_cookies)} кук(ов). Авторизация X активна.",
            "auth_token не найден после импорта. Скопируйте куки с x.com в залогиненном состоянии.",
        ),
        kwargs={"state_export_path": state_path},
        daemon=True,
    )
    t.start()
    return Response({"job_id": job_id})


# ── Threads cookie import ─────────────────────────────────────────────────────

def _threads_has_session() -> bool:
    return _check_cookie_in_profile(["threads.net", "threads.com"], ["sessionid"])


@api_view(["POST"])
def threads_import_cookies(request):
    raw = (request.data.get("cookies") or "").strip()
    if not raw:
        return Response({"error": "Поле cookies обязательно"}, status=400)
    try:
        pw_cookies = _parse_cookies_generic(raw, ["threads.net", "threads.com"], "sessionid", ".threads.net")
    except ValueError as e:
        return Response({"error": str(e)}, status=400)
    if not pw_cookies:
        return Response({"error": "Не найдено Threads-куков (нужен домен threads.net или threads.com)"}, status=400)

    state_path = str(Path(_get_profile_dir()) / "threads_state.json")
    job_id = _new_job()
    t = threading.Thread(
        target=_run_platform_cookie_import,
        args=(
            job_id, pw_cookies, _threads_has_session,
            f"Готово! Импортировано {len(pw_cookies)} кук(ов). Авторизация Threads активна.",
            "sessionid не найден после импорта. Скопируйте куки с threads.net в залогиненном состоянии.",
        ),
        kwargs={"state_export_path": state_path},
        daemon=True,
    )
    t.start()
    return Response({"job_id": job_id})


# ── Instagram browser auth ────────────────────────────────────────────────────

def _instagram_auth_url_still_in_progress(url: str) -> bool:
    """True while URL looks like login, 2FA, checkpoint, etc. (not a finished session)."""
    u = (url or "").lower()
    if "instagram.com" not in u:
        return True
    pending = (
        "accounts/login",
        "accounts/signup",
        "two_factor",
        "challenge",
        "checkpoint",
        "suspended",
        "consent",
        "accounts/onetap",
        "privacy/checkup",
        "accounts/account_recovery",
        "accounts/password",
    )
    return any(s in u for s in pending)


async def _instagram_has_sessionid_cookie(context) -> bool:
    cookies = await context.cookies("https://www.instagram.com")
    return any(
        c.get("name") == "sessionid" and "instagram" in (c.get("domain") or "").lower()
        for c in cookies
    )


async def _instagram_login_fully_complete(context, page) -> bool:
    if not await _instagram_has_sessionid_cookie(context):
        return False
    if _instagram_auth_url_still_in_progress(page.url):
        return False
    return True


def _run_instagram_auth(job_id: str) -> None:
    profile_dir = _prepare_browser_for_headed_auth(job_id)
    username = _get_setting("INSTAGRAM_USERNAME")
    password = _get_setting("INSTAGRAM_PASSWORD")
    session_file = _get_setting("INSTAGRAM_SESSION_FILE", "instagram.session")
    session_path = Path(session_file)
    if not session_path.is_absolute():
        session_path = Path(__file__).parent.parent / session_path

    async def _async():
        from playwright.async_api import async_playwright

        _set_job(job_id, "pending", "Запускаю браузер…")
        Path(profile_dir).mkdir(parents=True, exist_ok=True)

        async with async_playwright() as pw:
            ctx = await _launch_persistent_context(pw, profile_dir, headless=False, locale="ru-RU")
            try:
                page = ctx.pages[0] if ctx.pages else await ctx.new_page()

                _set_job(job_id, "pending", "Открываю Instagram…")
                await page.goto(
                    "https://www.instagram.com/",
                    wait_until="domcontentloaded",
                    timeout=_auth_nav_timeout_ms(),
                )
                await page.wait_for_timeout(2000)

                already_logged_in = await _instagram_login_fully_complete(ctx, page)

                if not already_logged_in:
                    _set_job(job_id, "pending", "Открываю страницу входа…")

                    # Auto-fill credentials (best-effort)
                    if username and password:
                        try:
                            await page.fill('input[name="username"]', username, timeout=4000)
                            await page.wait_for_timeout(400)
                            await page.fill('input[name="password"]', password, timeout=4000)
                            await page.wait_for_timeout(400)
                            await page.click('button[type="submit"]', timeout=4000)
                        except Exception:
                            pass

                    _set_job(
                        job_id,
                        "pending",
                        "Завершите вход (2FA, проверки Meta) в браузере. Окно не закроется, пока вход не будет полностью завершён.",
                    )

                    # До 30 мин: ждём sessionid и URL без login/challenge/2FA и т.д.
                    for _ in range(1800):
                        await asyncio.sleep(1)
                        if await _instagram_login_fully_complete(ctx, page):
                            break
                    else:
                        raise TimeoutError("Время ожидания входа истекло (30 мин).")

                # Give Instagram a moment to set all cookies
                await page.wait_for_timeout(2000)

                # Extract cookies and save as instaloader session
                _set_job(job_id, "pending", "Сохраняю сессию…")
                cookies = await ctx.cookies("https://www.instagram.com")

                import instaloader
                L = instaloader.Instaloader()
                sess = L.context._session
                for c in cookies:
                    if c.get("domain", "").endswith("instagram.com"):
                        sess.cookies.set(c["name"], c["value"], domain=".instagram.com")
                L.context.username = username or "unknown"
                L.save_session_to_file(str(session_path))

                # Воркер Instagram (Playwright) грузит instagram_state.json, а не instaloader .session.
                # Без этого открывается «чистый» Chromium без входа, хотя в persistent-профиле сессия есть.
                ig_state_path = Path(profile_dir) / "instagram_state.json"
                await ctx.storage_state(path=str(ig_state_path))

                _set_job(
                    job_id,
                    "done",
                    "Сессия Instagram сохранена (в т.ч. для окна обновления). Закройте окно браузера, когда закончите (окно не закроется само).",
                )
                try:
                    await ctx.wait_for_event("close", timeout=0)
                except Exception:
                    pass

            except Exception as e:
                _set_job(job_id, "error", f"Ошибка: {_format_headed_browser_error(e)}")
            finally:
                if ctx is not None:
                    try:
                        await ctx.close()
                    except Exception:
                        pass

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(_async())
    finally:
        loop.close()


@api_view(["POST"])
def instagram_start_auth(request):
    job_id = _new_job()
    t = threading.Thread(target=_run_instagram_auth, args=(job_id), daemon=True)
    t.start()
    return Response({"job_id": job_id})


# ── Telegram browser auth ─────────────────────────────────────────────────────

def _run_telegram_auth(job_id: str) -> None:
    profile_dir = _prepare_browser_for_headed_auth(job_id)

    async def _async():
        from playwright.async_api import async_playwright

        _set_job(job_id, "pending", "Запускаю браузер…")
        Path(profile_dir).mkdir(parents=True, exist_ok=True)

        async with async_playwright() as pw:
            ctx = await _launch_persistent_context(pw, profile_dir, headless=False, locale="ru-RU")
            try:
                page = ctx.pages[0] if ctx.pages else await ctx.new_page()

                _set_job(job_id, "pending", "Открываю Telegram Web…")
                await page.goto(
                    "https://web.telegram.org/k/",
                    wait_until="domcontentloaded",
                    timeout=_auth_nav_timeout_ms(),
                )

                # Wait for the app to paint something (auth page or main UI)
                await page.wait_for_timeout(3000)

                _IS_LOGGED_IN_JS = """
                    () => {
                        // Auth page visible → not logged in
                        const auth = document.querySelector('#auth-pages, .auth-page, .page-sign');
                        if (auth) {
                            const st = window.getComputedStyle(auth);
                            if (st.display !== 'none' && st.visibility !== 'hidden') return false;
                        }
                        // Any of these elements → logged in
                        return !!(
                            document.querySelector('#column-left')   ||
                            document.querySelector('.sidebar-left')  ||
                            document.querySelector('.chat-list')     ||
                            document.querySelector('.chatlist')      ||
                            document.querySelector('.dialogs-container') ||
                            document.querySelector('[class*="chatList"]') ||
                            document.querySelector('.im_dialogs')    ||
                            document.querySelector('.LeftColumn')
                        );
                    }
                """

                already_in = await page.evaluate(_IS_LOGGED_IN_JS)

                if not already_in:
                    _set_job(job_id, "pending", "Ожидаю входа в Telegram…")

                    # Poll up to 3 minutes for the main interface to appear
                    for _ in range(180):
                        await asyncio.sleep(1)
                        try:
                            if await page.evaluate(_IS_LOGGED_IN_JS):
                                break
                        except Exception:
                            pass
                    else:
                        raise TimeoutError("Время ожидания входа истекло (3 мин).")

                # Give the session a moment to fully persist
                await page.wait_for_timeout(2000)
                state_path = Path(profile_dir) / "telegram_state.json"
                await ctx.storage_state(path=str(state_path))
                _set_job(job_id, "done", "Вход в Telegram выполнен успешно!")

            except Exception as e:
                _set_job(job_id, "error", f"Ошибка: {_format_headed_browser_error(e)}")
            finally:
                if ctx is not None:
                    await ctx.close()

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(_async())
    finally:
        loop.close()


@api_view(["POST"])
def telegram_start_auth(request):
    job_id = _new_job()
    t = threading.Thread(target=_run_telegram_auth, args=(job_id), daemon=True)
    t.start()
    return Response({"job_id": job_id})


# ── X (Twitter) browser auth ──────────────────────────────────────────────────

def _run_x_auth(job_id: str) -> None:
    profile_dir = _prepare_browser_for_headed_auth(job_id)

    async def _async():
        from playwright.async_api import async_playwright

        _set_job(job_id, "pending", "Запускаю браузер…")
        Path(profile_dir).mkdir(parents=True, exist_ok=True)

        async with async_playwright() as pw:
            ctx = await _launch_persistent_context(pw, profile_dir, headless=False, locale="ru-RU")
            try:
                page = ctx.pages[0] if ctx.pages else await ctx.new_page()

                _set_job(job_id, "pending", "Открываю X…")
                await page.goto(
                    "https://x.com/home",
                    wait_until="domcontentloaded",
                    timeout=_auth_nav_timeout_ms(),
                )
                await page.wait_for_timeout(2000)

                _IS_LOGGED_IN_JS = """
                    () => {
                        const href = window.location.href;
                        if (href.includes('/i/flow/login') || href.includes('/login')) return false;
                        if (document.querySelector('[data-testid="loginButton"]')) return false;
                        return !!(
                            document.querySelector('[data-testid="SideNav_AccountSwitcher_Button"]') ||
                            document.querySelector('[data-testid="AppTabBar_Home_Link"]')
                        );
                    }
                """

                already_in = await page.evaluate(_IS_LOGGED_IN_JS)
                if not already_in:
                    _set_job(job_id, "pending", "Ожидаю входа в X…")
                    for _ in range(180):
                        await asyncio.sleep(1)
                        try:
                            if await page.evaluate(_IS_LOGGED_IN_JS):
                                break
                        except Exception:
                            pass
                    else:
                        raise TimeoutError("Время ожидания входа истекло (3 мин).")

                await page.wait_for_timeout(2000)
                state_path = Path(profile_dir) / "x_state.json"
                await ctx.storage_state(path=str(state_path))
                _set_job(job_id, "done", "Вход в X выполнен успешно!")

            except Exception as e:
                _set_job(job_id, "error", f"Ошибка: {_format_headed_browser_error(e)}")
            finally:
                if ctx is not None:
                    await ctx.close()

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(_async())
    finally:
        loop.close()


@api_view(["POST"])
def x_start_auth(request):
    job_id = _new_job()
    t = threading.Thread(target=_run_x_auth, args=(job_id), daemon=True)
    t.start()
    return Response({"job_id": job_id})


# ── Threads browser auth ──────────────────────────────────────────────────────

def _run_threads_auth(job_id: str) -> None:
    profile_dir = _prepare_browser_for_headed_auth(job_id)

    async def _async():
        from playwright.async_api import async_playwright

        _set_job(job_id, "pending", "Запускаю браузер…")
        Path(profile_dir).mkdir(parents=True, exist_ok=True)

        async with async_playwright() as pw:
            ctx = await _launch_persistent_context(pw, profile_dir, headless=False, locale="ru-RU")
            try:
                page = ctx.pages[0] if ctx.pages else await ctx.new_page()

                _set_job(job_id, "pending", "Открываю Threads…")
                await page.goto(
                    "https://www.threads.com/",
                    wait_until="domcontentloaded",
                    timeout=_auth_nav_timeout_ms(),
                )
                await page.wait_for_timeout(3000)

                # Click "Continue as …" button if it appears (Instagram session already exists)
                try:
                    continue_btn = await page.wait_for_selector(
                        'button:has-text("Continue"), button:has-text("Продолжить")',
                        timeout=4000,
                    )
                    if continue_btn:
                        await continue_btn.click()
                        await page.wait_for_timeout(3000)
                except Exception:
                    pass  # button not found, user may need to log in manually

                _IS_LOGGED_IN_JS = """
                    () => {
                        const href = window.location.href;
                        if (href.includes('/login')) return false;
                        if (document.querySelector('input[type="password"]') &&
                            document.querySelector('input[autocomplete="email"]')) return false;
                        return !!(
                            document.querySelector('[aria-label*="New thread"]')  ||
                            document.querySelector('[aria-label*="Новый тред"]')  ||
                            document.querySelector('[data-pressable-container]')
                        );
                    }
                """

                already_in = await page.evaluate(_IS_LOGGED_IN_JS)
                if not already_in:
                    _set_job(job_id, "pending", "Ожидаю входа в Threads…")
                    for _ in range(180):
                        await asyncio.sleep(1)
                        try:
                            if await page.evaluate(_IS_LOGGED_IN_JS):
                                break
                        except Exception:
                            pass
                    else:
                        raise TimeoutError("Время ожидания входа истекло (3 мин).")

                await page.wait_for_timeout(2000)
                state_path = Path(profile_dir) / "threads_state.json"
                await ctx.storage_state(path=str(state_path))
                _set_job(job_id, "done", "Вход в Threads выполнен успешно!")

            except Exception as e:
                _set_job(job_id, "error", f"Ошибка: {_format_headed_browser_error(e)}")
            finally:
                if ctx is not None:
                    await ctx.close()

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(_async())
    finally:
        loop.close()


@api_view(["POST"])
def threads_start_auth(request):
    job_id = _new_job()
    t = threading.Thread(target=_run_threads_auth, args=(job_id), daemon=True)
    t.start()
    return Response({"job_id": job_id})


# ── Facebook browser auth ─────────────────────────────────────────────────────

def _run_facebook_auth(job_id: str) -> None:
    profile_dir = _prepare_browser_for_headed_auth(job_id)
    email    = _get_setting("FACEBOOK_EMAIL")
    password = _get_setting("FACEBOOK_PASSWORD")

    async def _async():
        from playwright.async_api import async_playwright

        _set_job(job_id, "pending", "Запускаю браузер…")
        Path(profile_dir).mkdir(parents=True, exist_ok=True)

        async with async_playwright() as pw:
            ctx = await _launch_persistent_context(pw, profile_dir, headless=False, locale="ru-RU")
            try:
                page = ctx.pages[0] if ctx.pages else await ctx.new_page()

                _set_job(job_id, "pending", "Открываю Facebook…")
                await page.goto(
                    "https://www.facebook.com/",
                    wait_until="domcontentloaded",
                    timeout=_auth_nav_timeout_ms(),
                )
                await page.wait_for_timeout(2000)

                # Check if already logged in
                _IS_LOGGED_IN_JS = """
                    () => {
                        const url = window.location.href;
                        if (url.includes('/login') || url.includes('/checkpoint')) return false;
                        if (document.querySelector('input[name="email"]') &&
                            document.querySelector('input[name="pass"]')) return false;
                        return !!(
                            document.querySelector('[role="navigation"]') ||
                            document.querySelector('[aria-label="Facebook"]') ||
                            document.querySelector('[data-pagelet="LeftRail"]') ||
                            document.querySelector('[data-pagelet="Stories"]')
                        );
                    }
                """

                already_in = await page.evaluate(_IS_LOGGED_IN_JS)

                if not already_in:
                    _set_job(job_id, "pending", "Открываю страницу входа…")

                    # Navigate to login page if not already there
                    if "/login" not in page.url:
                        await page.goto(
                            "https://www.facebook.com/login/",
                            wait_until="domcontentloaded",
                            timeout=_auth_nav_timeout_ms(),
                        )
                        await page.wait_for_timeout(1500)

                    # Auto-fill credentials
                    if email and password:
                        try:
                            await page.fill('input[name="email"]', email, timeout=5000)
                            await page.wait_for_timeout(400)
                            await page.fill('input[name="pass"]', password, timeout=5000)
                            await page.wait_for_timeout(400)
                            await page.click('button[name="login"], button[type="submit"]',
                                             timeout=5000)
                            _set_job(job_id, "pending",
                                     "Вхожу в Facebook… (если появится капча — пройдите её)")
                        except Exception:
                            _set_job(job_id, "pending",
                                     "Войдите в Facebook в открытом окне браузера…")
                    else:
                        _set_job(job_id, "pending",
                                 "Войдите в Facebook в открытом окне браузера…")

                    # Poll for up to 3 minutes until logged in
                    for _ in range(180):
                        await asyncio.sleep(1)
                        try:
                            if await page.evaluate(_IS_LOGGED_IN_JS):
                                break
                        except Exception:
                            pass
                    else:
                        raise TimeoutError("Время ожидания входа истекло (3 мин).")

                # Give Facebook a moment to set all auth cookies
                await page.wait_for_timeout(2000)

                # Verify the key auth cookies are present
                if not _facebook_has_session():
                    raise RuntimeError(
                        "Куки Facebook (c_user) не обнаружены после входа. "
                        "Попробуйте войти ещё раз."
                    )

                state_path = Path(profile_dir) / "facebook_state.json"
                await ctx.storage_state(path=str(state_path))
                _set_job(job_id, "done", "Вход в Facebook выполнен успешно!")

            except Exception as e:
                _set_job(job_id, "error", f"Ошибка: {_format_headed_browser_error(e)}")
            finally:
                if ctx is not None:
                    await ctx.close()

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(_async())
    finally:
        loop.close()


@api_view(["POST"])
def facebook_start_auth(request):
    job_id = _new_job()
    t = threading.Thread(target=_run_facebook_auth, args=(job_id), daemon=True)
    t.start()
    return Response({"job_id": job_id})


# ── Facebook cookie import ────────────────────────────────────────────────────

@api_view(["POST"])
def facebook_import_cookies(request):
    raw = (request.data.get("cookies") or "").strip()
    if not raw:
        return Response({"error": "Поле cookies обязательно"}, status=400)
    try:
        pw_cookies = _parse_cookies_generic(
            raw, ["facebook.com"], "c_user", ".facebook.com"
        )
    except ValueError as e:
        return Response({"error": str(e)}, status=400)
    if not pw_cookies:
        return Response(
            {"error": "Не найдено Facebook-куков (нужен домен facebook.com)"},
            status=400,
        )

    state_path = str(Path(_get_profile_dir()) / "facebook_state.json")
    job_id = _new_job()
    t = threading.Thread(
        target=_run_platform_cookie_import,
        args=(
            job_id, pw_cookies, _facebook_has_session,
            f"Готово! Импортировано {len(pw_cookies)} кук(ов). Авторизация Facebook активна.",
            "c_user не найден после импорта. Скопируйте куки с facebook.com в залогиненном состоянии.",
        ),
        kwargs={"state_export_path": state_path},
        daemon=True,
    )
    t.start()
    return Response({"job_id": job_id})


# ── Rumble browser auth ────────────────────────────────────────────────────────

def _run_rumble_auth(job_id: str) -> None:
    profile_dir = _prepare_browser_for_headed_auth(job_id)

    async def _async():
        from playwright.async_api import async_playwright

        _set_job(job_id, "pending", "Запускаю браузер…")
        Path(profile_dir).mkdir(parents=True, exist_ok=True)

        async with async_playwright() as pw:
            ctx = await _launch_persistent_context(pw, profile_dir, headless=False, locale="ru-RU")
            try:
                page = ctx.pages[0] if ctx.pages else await ctx.new_page()
                _set_job(job_id, "pending", "Открываю Rumble…")
                await page.goto(
                    "https://rumble.com/",
                    wait_until="domcontentloaded",
                    timeout=_auth_nav_timeout_ms(),
                )
                await page.wait_for_timeout(2000)

                _set_job(
                    job_id,
                    "pending",
                    "Пройдите проверку/вход в открытом окне Rumble (если требуется)…",
                )

                for _ in range(180):
                    await asyncio.sleep(1)
                    if _rumble_has_session():
                        break
                else:
                    raise TimeoutError("Время ожидания истекло (3 мин). Не обнаружены cookies rumble.com.")

                state_path = Path(profile_dir) / "rumble_state.json"
                await ctx.storage_state(path=str(state_path))
                _set_job(job_id, "done", "Авторизация Rumble сохранена успешно!")
            except Exception as e:
                _set_job(job_id, "error", f"Ошибка: {_format_headed_browser_error(e)}")
            finally:
                if ctx is not None:
                    await ctx.close()

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(_async())
    finally:
        loop.close()


@api_view(["POST"])
def rumble_start_auth(request):
    job_id = _new_job()
    t = threading.Thread(target=_run_rumble_auth, args=(job_id), daemon=True)
    t.start()
    return Response({"job_id": job_id})


@api_view(["POST"])
def rumble_import_cookies(request):
    raw = (request.data.get("cookies") or "").strip()
    if not raw:
        return Response({"error": "Поле cookies обязательно"}, status=400)
    try:
        pw_cookies = _parse_cookies_generic(raw, ["rumble.com"], "cf_clearance", ".rumble.com")
    except ValueError as e:
        return Response({"error": str(e)}, status=400)
    if not pw_cookies:
        return Response(
            {"error": "Не найдено Rumble-куков (нужен домен rumble.com)"},
            status=400,
        )

    state_path = str(Path(_get_profile_dir()) / "rumble_state.json")
    job_id = _new_job()
    t = threading.Thread(
        target=_run_platform_cookie_import,
        args=(
            job_id, pw_cookies, _rumble_has_session,
            f"Готово! Импортировано {len(pw_cookies)} кук(ов). Авторизация Rumble активна.",
            "Cookies rumble.com не обнаружены после импорта. Скопируйте куки с rumble.com в залогиненном состоянии.",
        ),
        kwargs={"state_export_path": state_path},
        daemon=True,
    )
    t.start()
    return Response({"job_id": job_id})


# ── Reddit browser auth ────────────────────────────────────────────────────────

def _run_reddit_auth(job_id: str) -> None:
    profile_dir = _prepare_browser_for_headed_auth(job_id)

    async def _async():
        from playwright.async_api import async_playwright

        _set_job(job_id, "pending", "Запускаю браузер…")
        Path(profile_dir).mkdir(parents=True, exist_ok=True)

        async with async_playwright() as pw:
            ctx = await _launch_persistent_context(pw, profile_dir, headless=False, locale="ru-RU")
            try:
                page = ctx.pages[0] if ctx.pages else await ctx.new_page()
                _set_job(job_id, "pending", "Открываю Reddit…")
                await page.goto(
                    "https://www.reddit.com/login/",
                    wait_until="domcontentloaded",
                    timeout=_auth_nav_timeout_ms(),
                )
                await page.wait_for_timeout(2000)

                _set_job(
                    job_id,
                    "pending",
                    "Войдите в Reddit в открытом окне (если требуется 2FA/капча)…",
                )

                for _ in range(180):
                    await asyncio.sleep(1)
                    if _reddit_has_session():
                        break
                else:
                    raise TimeoutError("Время ожидания истекло (3 мин). Не обнаружена сессия Reddit.")

                state_path = Path(profile_dir) / "reddit_state.json"
                await ctx.storage_state(path=str(state_path))
                _set_job(job_id, "done", "Авторизация Reddit сохранена успешно!")
            except Exception as e:
                _set_job(job_id, "error", f"Ошибка: {_format_headed_browser_error(e)}")
            finally:
                if ctx is not None:
                    await ctx.close()

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(_async())
    finally:
        loop.close()


@api_view(["POST"])
def reddit_start_auth(request):
    job_id = _new_job()
    t = threading.Thread(target=_run_reddit_auth, args=(job_id), daemon=True)
    t.start()
    return Response({"job_id": job_id})


@api_view(["POST"])
def reddit_import_cookies(request):
    raw = (request.data.get("cookies") or "").strip()
    if not raw:
        return Response({"error": "Поле cookies обязательно"}, status=400)
    try:
        pw_cookies = _parse_cookies_generic(raw, ["reddit.com"], "reddit_session", ".reddit.com")
    except ValueError as e:
        return Response({"error": str(e)}, status=400)
    if not pw_cookies:
        return Response(
            {"error": "Не найдено Reddit-куков (нужен домен reddit.com)"},
            status=400,
        )

    state_path = str(Path(_get_profile_dir()) / "reddit_state.json")
    job_id = _new_job()
    t = threading.Thread(
        target=_run_platform_cookie_import,
        args=(
            job_id, pw_cookies, _reddit_has_session,
            f"Готово! Импортировано {len(pw_cookies)} кук(ов). Авторизация Reddit активна.",
            "reddit_session не найден после импорта. Скопируйте куки с reddit.com в залогиненном состоянии.",
        ),
        kwargs={"state_export_path": state_path},
        daemon=True,
    )
    t.start()
    return Response({"job_id": job_id})
