"""
Shared helpers for all Playwright scraper subprocess workers.

Key problem solved here:
    All workers previously shared one persistent Chrome profile.  When a platform
    detected the headless browser it could clear *all* cookies in that profile —
    wiping sessions for every other platform at once.  Additionally, some workers
    used channel="chrome" which opened the system Chrome (version > Playwright's
    Chromium), causing recurring CHROME_DELETE corruption.

Solution:
    • Each platform imports its cookies to a per-platform JSON state file
      (e.g. TikStatsChromeProfile/tiktok_state.json).
    • Workers load that file into an *ephemeral* (non-persistent) context — the
      platform can't write back to the profile, so it can't clear other sessions.
    • Fallback: if no state file exists, use the persistent profile as before
      (with auto-cleanup of CHROME_DELETE artefacts).
    • channel="chrome" removed everywhere — only Playwright's bundled Chromium is
      used, eliminating version-mismatch / CHROME_DELETE issues.

    • Демоны и одноразовый CLI Playwright по умолчанию не закрывают окно после
      ответа / EOF stdin (см. ``finish_cli_session_keep_browser_by_default``,
      ``WORKER_AUTOCLOSE_BROWSER_ON_EXIT``).
"""
import asyncio
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path


# ── Paths ──────────────────────────────────────────────────────────────────────

def default_profile_dir() -> Path:
    """
    Должен совпадать с BROWSER_PROFILE_DIR / ACCOUNTS_BROWSER_PROFILE_DIR:
    иначе вход в Settings и warm_tiktok_session пишут куки в один каталог,
    а воркер читает другой.
    """
    env = (os.environ.get("BROWSER_PROFILE_DIR") or "").strip()
    if env:
        return Path(env)
    try:
        from django.conf import settings as dj_settings

        raw = getattr(dj_settings, "ACCOUNTS_BROWSER_PROFILE_DIR", None)
        if raw:
            return Path(raw)
    except Exception:
        pass
    home = Path.home()
    if (home / "AppData").exists():          # Windows
        return home / "AppData" / "Local" / "TikStatsChromeProfile"
    return home / ".config" / "tikstats-chrome-profile"   # Linux / macOS


def state_file_path(platform: str, profile_dir: Path | None = None) -> Path:
    """Return the per-platform storage-state JSON path."""
    base = profile_dir or default_profile_dir()
    return base / f"{platform}_state.json"


def _playwright_root_has_chromium(root: Path) -> bool:
    """Есть ли в каталоге Playwright установленный Chromium (ms-playwright layout)."""
    if not root.is_dir():
        return False
    for child in root.iterdir():
        if not child.is_dir() or not child.name.startswith("chromium"):
            continue
        for sub, exe_name in (
            ("chrome-linux64", "chrome"),
            ("chrome-win64", "chrome.exe"),
            ("chrome-win", "chrome.exe"),
        ):
            exe = child / sub / exe_name
            if exe.is_file():
                return True
    return False


def default_playwright_browsers_path() -> Path | None:
    """Стандартный каталог браузеров Playwright на этой машине."""
    local = (os.environ.get("LOCALAPPDATA") or "").strip()
    if local:
        candidate = Path(local) / "ms-playwright"
        if _playwright_root_has_chromium(candidate):
            return candidate.resolve()
    home = Path.home()
    for rel in (
        ".cache/ms-playwright",
        "Library/Caches/ms-playwright",
        "AppData/Local/ms-playwright",
    ):
        candidate = (home / rel).resolve()
        if _playwright_root_has_chromium(candidate):
            return candidate
    return None


def _playwright_browsers_path_unusable(raw: str) -> bool:
    if not raw.strip():
        return True
    low = raw.replace("\\", "/").lower()
    if "cursor-sandbox-cache" in low or "/temp/cursor-" in low:
        return True
    return not _playwright_root_has_chromium(Path(raw))


def normalize_playwright_browsers_env(
    env: dict[str, str] | None = None,
    *,
    mutate_os_environ: bool = False,
) -> str | None:
    """
    Cursor sandbox задаёт PLAYWRIGHT_BROWSERS_PATH на cache без chromium — воркеры
    падают при launch. Подставляем ms-playwright или снимаем переменную.
    """
    store = os.environ if mutate_os_environ else (env if env is not None else os.environ)
    raw = (store.get("PLAYWRIGHT_BROWSERS_PATH") or "").strip()
    resolved: str | None = None
    if raw and not _playwright_browsers_path_unusable(raw):
        resolved = str(Path(raw).expanduser().resolve())
    else:
        default = default_playwright_browsers_path()
        if default is not None:
            resolved = str(default)
        elif mutate_os_environ or isinstance(store, dict):
            store.pop("PLAYWRIGHT_BROWSERS_PATH", None)
            return None
    if resolved:
        store["PLAYWRIGHT_BROWSERS_PATH"] = resolved
    return resolved


def _storage_state_has_instagram_session(path: Path) -> bool:
    """instagram_state.json без sessionid даёт «пустой» браузер — не используем такой файл."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return False
    for c in data.get("cookies") or []:
        dom = (c.get("domain") or "").lower()
        if c.get("name") == "sessionid" and "instagram" in dom:
            return True
    return False


# ── Chrome artefact cleanup ────────────────────────────────────────────────────

def accounts_profile_roots() -> list[Path]:
    """Каталоги user-data-dir Playwright (общий профиль и *_persistent по платформам)."""
    try:
        from django.conf import settings as dj_settings

        raw = getattr(dj_settings, "ACCOUNTS_BROWSER_PROFILE_DIR", None)
        base = Path(raw) if raw else default_profile_dir()
    except Exception:
        base = default_profile_dir()
    base = base.expanduser().resolve()
    roots = [base]
    if base.is_dir():
        for child in base.iterdir():
            if child.is_dir() and child.name.endswith("_persistent"):
                roots.append(child)
    return roots


def chrome_cmdline_matches_user_data_dir(cmdline: str, profile_dir: Path | str) -> bool:
    """
    True, если процесс Chrome использует ровно этот user-data-dir (не подкаталог).
    Нужно для параллельного warm_tiktok (tiktok_chrome_*) и warm_facebook (base / *_persistent).
    """
    if not cmdline:
        return False
    prof = str(Path(profile_dir).expanduser().resolve())
    if not prof:
        return False
    low = cmdline.replace("\\", "/")
    prof_fwd = prof.replace("\\", "/").rstrip("/")
    for prefix in (
        f"--user-data-dir={prof_fwd}",
        f'--user-data-dir="{prof_fwd}"',
        f"--user-data-dir='{prof_fwd}'",
    ):
        if prefix not in low:
            continue
        idx = low.find(prefix) + len(prefix)
        if idx >= len(low):
            return True
        nxt = low[idx]
        if nxt in " \t\"'":
            return True
    return False


def kill_chrome_processes_for_profile(profile_dir: Path | str) -> None:
    """
    Завершить Chromium/Chrome, привязанные к user-data-dir (после terminate() воркера
    дочерний браузер на macOS/Windows часто остаётся в доке).
    """
    path = str(Path(profile_dir).expanduser().resolve())
    if not path:
        return

    if os.name == "nt":
        needle = path.replace("'", "''")
        esc = needle.replace("\\", "\\\\")
        for exe in ("chrome.exe", "chromium.exe"):
            ps = (
                f"$esc = [regex]::Escape('{esc}'); "
                f"Get-CimInstance Win32_Process -Filter \"name='{exe}'\" -ErrorAction SilentlyContinue | "
                "Where-Object { "
                "  $_.CommandLine -and "
                "  ($_.CommandLine -match ('--user-data-dir=\"?' + $esc + '\"?(\\s|$)')) "
                "} | "
                "ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
            )
            try:
                subprocess.run(
                    ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
                    check=False,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=25,
                )
            except Exception:
                pass
        return

    try:
        out = subprocess.run(
            ["ps", "-ax", "-o", "pid=,command="],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        if out.returncode == 0 and out.stdout:
            for line in out.stdout.splitlines():
                line = line.strip()
                if not line:
                    continue
                parts = line.split(None, 1)
                if len(parts) < 2:
                    continue
                pid_s, cmd = parts[0], parts[1]
                if not chrome_cmdline_matches_user_data_dir(cmd, path):
                    continue
                try:
                    subprocess.run(
                        ["kill", "-9", pid_s],
                        check=False,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        timeout=5,
                    )
                except Exception:
                    pass
    except Exception:
        for pat in (f"--user-data-dir={path}", f'--user-data-dir="{path}"'):
            try:
                subprocess.run(
                    ["pkill", "-f", pat],
                    check=False,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=10,
                )
            except Exception:
                pass


def kill_chrome_profile_roots(
    roots: list[Path] | tuple[Path, ...],
    *,
    cleanup_artifacts: bool = False,
) -> None:
    """Снять Chromium только для указанных user-data-dir (не трогать FB/IG и общий профиль)."""
    seen: set[str] = set()
    for root in roots:
        key = str(Path(root).expanduser().resolve())
        if key in seen:
            continue
        seen.add(key)
        kill_chrome_processes_for_profile(root)
        if cleanup_artifacts:
            cleanup_chrome_artifacts(root)


def kill_all_accounts_profile_chrome(*, cleanup_artifacts: bool = True) -> None:
    """Снять все Chromium, связанные с профилем дашборда (перед/после пула воркеров)."""
    seen: set[str] = set()
    for root in accounts_profile_roots():
        key = str(root)
        if key in seen:
            continue
        seen.add(key)
        kill_chrome_processes_for_profile(root)
        if cleanup_artifacts:
            cleanup_chrome_artifacts(root)


def _cmdline_matches_worker_daemon(
    cmdline: str,
    *,
    backend_root_norm: str,
    worker_script_norm: str | None,
) -> bool:
    low = (cmdline or "").replace("\\", "/").lower()
    if not low or backend_root_norm not in low:
        return False
    if "worker.py" not in low or "--daemon" not in low:
        return False
    if worker_script_norm is not None:
        return worker_script_norm in low
    return "/platforms/" in low or "\\platforms\\" in (cmdline or "").lower()


def find_dashboard_worker_daemon_pids(
    backend_root: Path,
    *,
    worker_script: Path | None = None,
) -> list[int]:
    """
    PID процессов ``platforms/*/worker.py --daemon`` этого backend (не из пула).
    """
    root = backend_root.expanduser().resolve()
    root_norm = str(root).replace("\\", "/").lower()
    script_norm = (
        str(worker_script.expanduser().resolve()).replace("\\", "/").lower()
        if worker_script is not None
        else None
    )
    pids: list[int] = []

    if os.name == "nt":
        escaped = str(root).replace("'", "''")
        ps = (
            f"$root = '{escaped}'.ToLower().Replace('\\','/'); "
            "Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | "
            "Where-Object { "
            "$cl = $_.CommandLine; "
            "if (-not $cl) { return $false }; "
            "$low = $cl.ToLower().Replace('\\','/'); "
            "if (-not $low.Contains($root)) { return $false }; "
            "if ($low -notlike '*worker.py*' -or $low -notlike '*--daemon*') { return $false }; "
        )
        if script_norm is not None:
            esc_script = script_norm.replace("'", "''")
            ps += f"if (-not $low.Contains('{esc_script}')) {{ return $false }}; "
        else:
            ps += "if ($low -notlike '*/platforms/*') { return $false }; "
        ps += "return $true } | Select-Object -ExpandProperty ProcessId"
        try:
            proc = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=30,
                check=False,
            )
            for line in (proc.stdout or "").splitlines():
                line = line.strip()
                if line.isdigit():
                    pids.append(int(line))
        except Exception:
            pass
        return sorted(set(pids))

    try:
        out = subprocess.run(
            ["ps", "-eo", "pid=,args="],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=20,
            check=False,
        )
        for line in (out.stdout or "").splitlines():
            line = line.strip()
            if not line:
                continue
            parts = line.split(None, 1)
            if len(parts) < 2 or not parts[0].isdigit():
                continue
            pid = int(parts[0])
            args = parts[1]
            if _cmdline_matches_worker_daemon(
                args,
                backend_root_norm=root_norm,
                worker_script_norm=script_norm,
            ):
                pids.append(pid)
    except Exception:
        pass
    return sorted(set(pids))


def win32_parent_process_id(pid: int) -> int | None:
    if os.name != "nt" or pid <= 0:
        return None
    try:
        proc = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                f"(Get-CimInstance Win32_Process -Filter \"ProcessId={int(pid)}\" "
                "-ErrorAction SilentlyContinue | Select-Object -ExpandProperty ParentProcessId)",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
            check=False,
        )
        line = (proc.stdout or "").strip().splitlines()[0].strip() if (proc.stdout or "").strip() else ""
        return int(line) if line.isdigit() else None
    except Exception:
        return None


def pid_is_descendant_of(child_pid: int, ancestor_pid: int, *, max_depth: int = 16) -> bool:
    """True, если child_pid в дереве процессов ancestor_pid."""
    if child_pid <= 0 or ancestor_pid <= 0:
        return False
    current = int(child_pid)
    for _ in range(max_depth):
        if current == int(ancestor_pid):
            return True
        parent = win32_parent_process_id(current) if os.name == "nt" else None
        if parent is None or parent <= 0:
            if os.name != "nt":
                try:
                    import psutil  # optional

                    p = psutil.Process(current)
                    parent = int(p.ppid())
                except Exception:
                    return False
            else:
                return False
        current = int(parent)
    return False


def live_dashboard_runserver_pids(backend_root: Path) -> set[int]:
    """Живые manage.py runserver этого backend (не убивать их дочерние worker --daemon)."""
    root = backend_root.expanduser().resolve()
    root_norm = str(root).replace("\\", "/").lower()
    pids: set[int] = set()
    if os.name == "nt":
        escaped = str(root).replace("'", "''")
        ps = (
            f"$root = '{escaped}'.ToLower().Replace('\\','/'); "
            "Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | "
            "Where-Object { "
            "$cl = $_.CommandLine; "
            "if (-not $cl) { return $false }; "
            "$low = $cl.ToLower().Replace('\\','/'); "
            "if (-not $low.Contains($root)) { return $false }; "
            "if ($low -notlike '*manage.py*runserver*') { return $false }; "
            "return $true } | Select-Object -ExpandProperty ProcessId"
        )
        try:
            proc = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=30,
                check=False,
            )
            for line in (proc.stdout or "").splitlines():
                line = line.strip()
                if line.isdigit():
                    pids.add(int(line))
        except Exception:
            pass
        return pids
    try:
        out = subprocess.run(
            ["ps", "-eo", "pid=,args="],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=20,
            check=False,
        )
        for line in (out.stdout or "").splitlines():
            parts = line.strip().split(None, 1)
            if len(parts) < 2 or not parts[0].isdigit():
                continue
            args = parts[1].replace("\\", "/").lower()
            if root_norm in args and "manage.py" in args and "runserver" in args:
                pids.add(int(parts[0]))
    except Exception:
        pass
    return pids


def kill_worker_process_pids(pids: list[int]) -> int:
    """Завершить процессы воркеров по PID. Возвращает число успешных kill."""
    killed = 0
    for pid in pids:
        if pid <= 0:
            continue
        try:
            if os.name == "nt":
                subprocess.run(
                    ["taskkill", "/PID", str(pid), "/F"],
                    check=False,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=15,
                )
            else:
                os.kill(pid, 9)
            killed += 1
        except Exception:
            pass
    return killed


def release_chromium_profile_lock(profile_dir: Path | str) -> None:
    """Снять SingletonLock и зависший Chrome перед launch_persistent_context."""
    base = Path(profile_dir)
    for name in ("SingletonLock", "SingletonCookie", "SingletonSocket"):
        p = base / name
        try:
            if p.exists() or p.is_symlink():
                p.unlink()
                print(f"[worker_utils] removed profile lock: {name}", file=sys.stderr)
        except Exception as exc:
            print(f"[worker_utils] could not remove {name}: {exc}", file=sys.stderr)
    kill_chrome_processes_for_profile(base)
    cleanup_chrome_artifacts(base)


def cleanup_chrome_artifacts(profile_dir: Path) -> None:
    """
    Remove stale .CHROME_DELETE / Snapshots artefacts that prevent Chrome from
    launching.  These are left behind when Chrome detects a version downgrade and
    fails to complete the clean-up (e.g. because the target path already exists).
    """
    if not profile_dir.exists():
        return
    for entry in profile_dir.iterdir():
        if entry.name.endswith(".CHROME_DELETE") or entry.name == "Snapshots":
            try:
                shutil.rmtree(entry, ignore_errors=True)
                print(f"[worker_utils] removed artefact: {entry.name}", file=sys.stderr)
            except Exception as exc:
                print(f"[worker_utils] cleanup failed for {entry.name}: {exc}",
                      file=sys.stderr)


# ── Context launcher ──────────────────────────────────────────────────────────

# A non-headless user-agent for Chromium (hides "HeadlessChrome" which most
# platforms use as a bot signal).
_UA_CHROME = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/145.0.7632.6 Safari/537.36"
)

_STEALTH_CHROMIUM_ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--disable-features=AutomationControlled",
]
_SAFE_CHROME_ARGS = [
    "--no-first-run",
    "--no-default-browser-check",
    "--disable-default-apps",
]
# Обратная совместимость (bundled Chromium без channel).
_COMMON_ARGS = list(_STEALTH_CHROMIUM_ARGS) + list(_SAFE_CHROME_ARGS)


def chromium_launch_args(
    *,
    channel: str | None = None,
    hide_automation: bool = True,
    extra: list[str] | None = None,
) -> list[str]:
    """
    Аргументы Chrome для Playwright.

    Системный Chrome (channel=chrome/msedge) не принимает CLI-флаги
    AutomationControlled — маскировка только через init_script.
    """
    use_system = bool(str(channel or "").strip())
    args: list[str] = []
    if hide_automation and not use_system:
        args.extend(_STEALTH_CHROMIUM_ARGS)
    args.extend(_SAFE_CHROME_ARGS)
    if extra:
        for a in extra:
            if a and a not in args:
                args.append(a)
    return args

# Playwright по умолчанию добавляет, среди прочего:
# --enable-automation → плашка «автоматизированное тестовое ПО»;
# --no-sandbox → предупреждение в обычном Chrome на Windows (channel=chrome).
def _playwright_default_args_to_ignore() -> list[str]:
    ignored = ["--enable-automation"]
    if os.name == "nt":
        ignored.append("--no-sandbox")
    return ignored


def playwright_ignore_automation_defaults(*, enabled: bool = True) -> dict[str, list[str]]:
    if not enabled:
        return {}
    return {"ignore_default_args": _playwright_default_args_to_ignore()}

# Injected before every page load to remove automation fingerprints.
_STEALTH_SCRIPT = """
    (() => {
        // Remove navigator.webdriver flag
        Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
        // Simulate a real chrome object
        if (!window.chrome) {
            window.chrome = { runtime: {}, loadTimes: function(){}, csi: function(){}, app: {} };
        }
        // Spoof plugin length (headless has 0 plugins)
        Object.defineProperty(navigator, 'plugins', {
            get: () => { const p = [1,2,3,4,5]; p.item = () => null; p.namedItem = () => null; p.refresh = () => null; return p; }
        });
        // Spoof languages
        Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
    })();
"""


_CHALLENGE_JS = r"""
() => {
    const title = (document.title || '').toLowerCase();
    const href = (location.href || '').toLowerCase();
    const body = (document.body?.innerText || '').toLowerCase();
    if (
        title.includes('just a moment') ||
        title.includes('attention required') ||
        href.includes('challenge') ||
        body.includes('checking your browser') ||
        body.includes('verify you are human') ||
        body.includes('verify you are a human')
    ) {
        return true;
    }
    // TikTok / ByteDance: слайдер, puzzle, «подтвердите…»
    if (
        href.includes('captcha') ||
        href.includes('/verify') ||
        body.includes('captcha') ||
        body.includes('verify to continue') ||
        body.includes('drag the slider') ||
        (body.includes('подтвердите') && (
            body.includes('робот') || body.includes('личност') || body.includes('человек')
        )) ||
        (body.includes('перетащите') && body.includes('ползун'))
    ) {
        return true;
    }
    try {
        if (document.querySelector(
            '#captcha-verify-container, #captcha_container, '
            + '[class*="captcha"], [class*="Captcha"], [data-e2e*="captcha"]'
        )) {
            return true;
        }
        for (const f of document.querySelectorAll('iframe')) {
            const s = (f.getAttribute('src') || '').toLowerCase();
            if (s.includes('captcha') || s.includes('verify')) return true;
        }
    } catch (_) {}
    return false;
}
"""


def anti_bot_wait_timeout_ms(platform: str) -> int:
    """Сколько ждать ручного прохождения капчи/челленджа (мс)."""
    plat = (platform or "").strip().lower()
    if plat == "tiktok":
        raw = os.environ.get("TIKTOK_CAPTCHA_WAIT_MS", "300000")
    else:
        raw = os.environ.get("ANTI_BOT_WAIT_MS", "120000")
    try:
        return max(30_000, int(str(raw).strip()))
    except (TypeError, ValueError):
        return 300_000 if plat == "tiktok" else 120_000

# Встроенная страница Chromium «Доступ запрещён / HTTP ERROR 403» (не Cloudflare).
_CHROMIUM_403_JS = r"""
() => {
    const body = (document.body?.innerText || '').toLowerCase();
    const title = (document.title || '').toLowerCase();
    return (
        body.includes('http error 403') ||
        body.includes('ошибка http 403') ||
        body.includes('у вас нет прав для просмотра') ||
        body.includes('access to www.tiktok.com was denied') ||
        body.includes('access denied') ||
        (body.includes('403') && (
            body.includes('запрещ') ||
            body.includes('forbidden') ||
            body.includes('denied')
        )) ||
        title.includes('403')
    );
}
"""


_TRUE_VALUES = frozenset({"1", "true", "yes", "on", "y"})
_FALSE_VALUES = frozenset({"0", "false", "no", "off", "n"})


def _env_bool(name: str, default: bool = False) -> bool | None:
    """Распарсить env-переменную как bool. Пустое/неустановленное → None."""
    raw = os.environ.get(name)
    if raw is None:
        return None
    s = raw.strip().lower()
    if s == "":
        return None
    if s in _TRUE_VALUES:
        return True
    if s in _FALSE_VALUES:
        return False
    return default


def _resolve_headless_windows(
    *,
    platform: str | None,
    fallback: bool,
) -> bool:
    """
    Локальная Windows — как на последнем рабочем коммите:
    BROWSER_HEADLESS из .env, затем ACCOUNTS_BROWSER_HEADLESS из worker_accounts.env.
    """
    if platform:
        per_platform = _env_bool(f"{platform.upper()}_HEADLESS")
        if per_platform is not None:
            return per_platform
    glob = _env_bool("BROWSER_HEADLESS")
    if glob is not None:
        return glob
    try:
        from django.conf import settings as dj_settings

        acc = getattr(dj_settings, "ACCOUNTS_BROWSER_HEADLESS", None)
        if acc is not None:
            return bool(acc)
    except Exception:
        pass
    return fallback


def _resolve_headless_linux(
    *,
    platform: str | None,
    fallback: bool,
) -> bool:
    """
    Linux-сервер (Docker / RDP): worker_accounts.env важнее compose BROWSER_HEADLESS=true.
    Без явных env на Mobile Farm с DISPLAY — headed, если MOBILEFARM_DISPLAY задан.
    """
    if platform:
        per_platform = _env_bool(f"{platform.upper()}_HEADLESS")
        if per_platform is not None:
            return per_platform
    try:
        from django.conf import settings as dj_settings

        acc = getattr(dj_settings, "ACCOUNTS_BROWSER_HEADLESS", None)
        if acc is not None:
            return bool(acc)
    except Exception:
        pass
    glob = _env_bool("BROWSER_HEADLESS")
    if glob is not None:
        return glob
    try:
        from platforms.host_os import linux_prefers_headed_browser

        if linux_prefers_headed_browser():
            return False
    except Exception:
        pass
    if fallback is not False:
        return fallback
    return True


def resolve_headless(
    *,
    platform: str | None = None,
    fallback: bool = False,
) -> bool:
    """Headless для Playwright: отдельная логика Windows vs Linux."""
    from platforms.host_os import is_linux, is_windows

    if is_windows():
        return _resolve_headless_windows(platform=platform, fallback=fallback)
    if is_linux():
        return _resolve_headless_linux(platform=platform, fallback=fallback)
    return _resolve_headless_windows(platform=platform, fallback=fallback)


async def launch_context(
    pw,
    *,
    platform: str,
    profile_dir: Path | None = None,
    headless: bool | None = None,
    locale: str = "en-US",
    viewport: dict | None = None,
    force_persistent: bool = False,
    extra_args: list | None = None,
    browser_channel: str | None = None,
):
    """
    Launch the right kind of Playwright browser context for ``platform``.

    Priority:
    1. ``{profile_dir}/{platform}_state.json`` exists →
       ephemeral (non-persistent) context loaded from that file.
       The platform sees valid cookies but cannot write back to the profile;
       other platforms' sessions are safe.

    2. Fallback → persistent context from ``profile_dir`` (with auto-retry
       after removing CHROME_DELETE artefacts on first failure).

    Returns
    -------
    (context, browser_or_none)
        If browser_or_none is not None the caller must close both context and
        browser.  If None, closing context is sufficient.
    """
    if viewport is None:
        viewport = {"width": 1280, "height": 900}

    if headless is None:
        headless = resolve_headless(platform=platform)

    init_script = _STEALTH_SCRIPT
    user_agent = _UA_CHROME
    if platform == "facebook":
        from platforms.facebook.browser_profile import (
            build_stealth_script,
            context_options,
            launch_args,
            load_profile,
        )

        bp = load_profile()
        co = context_options(bp)
        locale = str(co.get("locale") or locale)
        viewport = dict(co.get("viewport") or viewport)
        user_agent = str(co.get("user_agent") or user_agent)
        extra_args = list(extra_args or []) + list(launch_args(bp, channel=browser_channel))
        if bp.get("stealth_enabled", True):
            init_script = build_stealth_script(bp.get("languages") or [])

    base = profile_dir or default_profile_dir()
    print(f"[{platform}_worker] launch_context headless={headless}", file=sys.stderr)
    sf = state_file_path(platform, base)

    ig_state_broken = (
        platform == "instagram"
        and sf.exists()
        and not _storage_state_has_instagram_session(sf)
    )
    if ig_state_broken:
        print(
            f"[{platform}_worker] {sf.name} без sessionid Instagram — игнорирую, "
            "беру persistent profile (или заново войдите в Instagram в настройках).",
            file=sys.stderr,
        )
    elif not sf.exists():
        print(
            f"[{platform}_worker] WARNING: state file not found at {sf} — "
            "falling back to persistent profile. "
            "Import cookies via Settings to create the state file.",
            file=sys.stderr,
        )

    hide_auto = True
    if platform == "facebook":
        hide_auto = bool(bp.get("hide_automation_flags", True))
    all_args = chromium_launch_args(
        channel=browser_channel,
        hide_automation=hide_auto,
        extra=list(extra_args or []),
    )
    if not headless:
        all_args.append("--start-maximized")

    use_storage_state = sf.exists() and not force_persistent and not ig_state_broken

    if use_storage_state and platform == "facebook":
        # Persistent-каталог в AccountsStats-профиле: его видит kill при пересоздании
        # демона (в отличие от временного user-data-dir у chromium.launch).
        launch_dir = base / "facebook_from_state"
        launch_dir.mkdir(parents=True, exist_ok=True)
        release_chromium_profile_lock(launch_dir)
        print(
            f"[{platform}_worker] loading state from {sf.name} → {launch_dir.name}/",
            file=sys.stderr,
        )
        hide_infobar = bool(bp.get("hide_automation_flags", True))
        context = await pw.chromium.launch_persistent_context(
            str(launch_dir),
            headless=headless,
            args=all_args,
            locale=locale,
            viewport=viewport,
            user_agent=user_agent,
            channel=browser_channel,
            **playwright_ignore_automation_defaults(enabled=hide_infobar),
        )
        await context.add_init_script(init_script)
        try:
            state_data = json.loads(sf.read_text(encoding="utf-8"))
            cookies = state_data.get("cookies") or []
            if cookies:
                await context.add_cookies(cookies)
        except Exception as exc:
            print(
                f"[{platform}_worker] не удалось подставить cookies из {sf.name}: {exc}",
                file=sys.stderr,
            )
        return context, None

    if use_storage_state:
        print(f"[{platform}_worker] loading state from {sf.name}", file=sys.stderr)
        launch_kwargs = {
            "headless": headless,
            "args": all_args,
            **playwright_ignore_automation_defaults(),
        }
        if browser_channel:
            launch_kwargs["channel"] = browser_channel
        browser = await pw.chromium.launch(**launch_kwargs)
        context = await browser.new_context(
            storage_state=str(sf),
            locale=locale,
            viewport=viewport,
            user_agent=user_agent,
        )
        await context.add_init_script(init_script)
        return context, browser   # caller must close browser too

    # ── Fallback: persistent profile ──────────────────────────────────────────
    if not force_persistent and not use_storage_state:
        print(
            f"[{platform}_worker] using persistent profile "
            f"(import cookies via Settings to protect other sessions)",
            file=sys.stderr,
        )
    base.mkdir(parents=True, exist_ok=True)
    isolated = base / f"{platform}_persistent"
    # Два кандидата user-data-dir: общий профиль и изолированный каталог платформы.
    # Раньше второй был только при force_persistent — Threads и др. без state при занятом
    # `base` (Facebook/Telegram) не имели fallback и плодились лишние Chromium при ретраях пула.
    launch_dirs = [base, isolated]

    for launch_dir in launch_dirs:
        launch_dir.mkdir(parents=True, exist_ok=True)
        for attempt in range(2):
            try:
                hide_infobar = True
                if platform == "facebook":
                    hide_infobar = bool(bp.get("hide_automation_flags", True))
                context = await pw.chromium.launch_persistent_context(
                    str(launch_dir),
                    headless=headless,
                    args=all_args,
                    locale=locale,
                    viewport=viewport,
                    user_agent=user_agent,
                    channel=browser_channel,
                    **playwright_ignore_automation_defaults(enabled=hide_infobar),
                )
                await context.add_init_script(init_script)
                return context, None   # caller closes context only
            except Exception as exc:
                if attempt == 0:
                    print(
                        f"[{platform}_worker] launch failed ({exc}); "
                        "cleaning Chrome artefacts and retrying…",
                        file=sys.stderr,
                    )
                    cleanup_chrome_artifacts(launch_dir)
                else:
                    if launch_dir != launch_dirs[-1]:
                        print(
                            f"[{platform}_worker] shared profile busy; "
                            f"retrying with isolated profile: {launch_dir.name}",
                            file=sys.stderr,
                        )
                        await asyncio.sleep(1.2)
                        break
                    raise


async def close_context(context, browser) -> None:
    """Close context (and browser if we own it)."""
    try:
        await context.close()
    except Exception:
        pass
    if browser is not None:
        try:
            await browser.close()
        except Exception:
            pass


def worker_autoclose_browser_on_daemon_exit() -> bool:
    """
    Если True — при завершении цикла stdin **демона** или после **одноразового CLI**
    вызывается ``close_context`` и процесс может завершиться.
    По умолчанию False: одно окно/вкладка на платформу остаётся открытым; завершите
    процесс вручную (Ctrl+C, остановка Django, ``shutdown_all_workers``) или задайте
    эту переменную для CI/автотестов.
    """
    return os.getenv("WORKER_AUTOCLOSE_BROWSER_ON_EXIT", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
        "y",
    }


_DAEMON_HOME_URL: dict[str, str] = {
    "tiktok": "https://www.tiktok.com/",
    "instagram": "https://www.instagram.com/",
    "threads": "https://www.threads.com/",
    "x": "https://x.com/home",
    "facebook": "https://www.facebook.com/",
}


async def _click_chromium_reload_button(page) -> bool:
    """Кнопка «Перезагрузить» на встроенной странице ошибки Chromium."""
    for label in ("Перезагрузить", "Reload"):
        try:
            btn = page.get_by_role("button", name=label)
            if await btn.count() > 0:
                await btn.first.click(timeout=5000)
                return True
        except Exception:
            continue
    try:
        return bool(
            await page.evaluate(
                """() => {
                    const labels = ['перезагруз', 'reload'];
                    for (const el of document.querySelectorAll('button, [role="button"]')) {
                        const t = (el.innerText || el.textContent || '').toLowerCase();
                        if (labels.some((l) => t.includes(l))) {
                            el.click();
                            return true;
                        }
                    }
                    return false;
                }""",
            ),
        )
    except Exception:
        return False


async def page_is_chromium_http_403(page) -> bool:
    """Встроенная страница Chrome «Доступ запрещён / HTTP ERROR 403»."""
    try:
        u = (page.url or "").lower()
        if u.startswith("chrome-error://"):
            return True
        return bool(await page.evaluate(_CHROMIUM_403_JS))
    except Exception:
        return False


async def recover_from_chromium_http_403(
    page,
    *,
    platform: str = "tiktok",
    target_url: str | None = None,
    wait_before_click_ms: int = 5000,
    max_cycles: int = 4,
) -> bool:
    """
    Снять interstitial HTTP 403: «Перезагрузить», reload, затем заход на главную и снова target_url.
    Возвращает True, если страница больше не 403.
    """
    plat = (platform or "worker").strip().lower()
    handled = False
    for cycle in range(max_cycles):
        if not await page_is_chromium_http_403(page):
            return True
        handled = True
        print(
            f"[{plat}_worker] Chrome HTTP 403 — ждём {wait_before_click_ms / 1000:.0f} с "
            f"и «Перезагрузить» ({cycle + 1}/{max_cycles}), url={page.url!r}",
            file=sys.stderr,
        )
        await page.wait_for_timeout(wait_before_click_ms)
        clicked = await _click_chromium_reload_button(page)
        if clicked:
            try:
                await page.wait_for_load_state("domcontentloaded", timeout=45_000)
            except Exception:
                pass
        else:
            try:
                await page.reload(wait_until="domcontentloaded", timeout=45_000)
            except Exception as exc:
                print(f"[{plat}_worker] HTTP 403: reload() не удался: {exc}", file=sys.stderr)
        await page.wait_for_timeout(1500)
        if not await page_is_chromium_http_403(page):
            return True
        # Прямой goto на профиль часто ловит 403 «холодным» Chrome — сначала главная с куками.
        try:
            await page.goto(
                "https://www.tiktok.com/",
                wait_until="domcontentloaded",
                timeout=45_000,
            )
            await page.wait_for_timeout(2000)
        except Exception as exc:
            print(f"[{plat}_worker] HTTP 403: warm home failed: {exc}", file=sys.stderr)
        if target_url and "tiktok.com" in target_url.lower():
            try:
                await page.goto(
                    target_url,
                    wait_until="domcontentloaded",
                    timeout=45_000,
                )
                await page.wait_for_timeout(1500)
            except Exception as exc:
                print(f"[{plat}_worker] HTTP 403: re-goto {target_url!r}: {exc}", file=sys.stderr)
    return not await page_is_chromium_http_403(page)


async def try_dismiss_chromium_http_403(
    page,
    *,
    platform: str,
    wait_before_click_ms: int = 5000,
    max_attempts: int = 3,
    target_url: str | None = None,
) -> bool:
    """Обёртка для совместимости; предпочтительно recover_from_chromium_http_403."""
    if not await page_is_chromium_http_403(page):
        return False
    return await recover_from_chromium_http_403(
        page,
        platform=platform,
        target_url=target_url,
        wait_before_click_ms=wait_before_click_ms,
        max_cycles=max_attempts,
    )


async def tiktok_goto_with_403_recovery(
    page,
    url: str,
    *,
    timeout_ms: int = 45_000,
) -> None:
    """page.goto + 403 recovery + ожидание капчи TikTok в открытом окне."""
    target = (url or "").strip()
    await page.goto(target, wait_until="domcontentloaded", timeout=timeout_ms)
    await recover_from_chromium_http_403(
        page,
        platform="tiktok",
        target_url=target,
    )
    await wait_for_anti_bot_clear(page, platform="tiktok")


async def warm_playwright_page_home(page, platform: str) -> None:
    """Открыть домашнюю страницу площадки вместо about:blank (белый экран в окне worker)."""
    plat = str(platform or "").strip().lower()
    url = _DAEMON_HOME_URL.get(plat)
    if not url:
        return
    try:
        if page is None or page.is_closed():
            return
        if plat == "tiktok":
            await tiktok_goto_with_403_recovery(page, url, timeout_ms=45_000)
        else:
            await page.goto(url, wait_until="domcontentloaded", timeout=45_000)
        await page.wait_for_timeout(500)
    except Exception as exc:
        print(f"[audience] warm {plat} home: {exc}", file=sys.stderr)


async def daemon_idle_keep_browser_open(
    worker_label: str,
    page=None,
    *,
    platform: str | None = None,
) -> None:
    """
    После EOF stdin не закрываем Chromium: блокируемся, пока процесс не убьют.
    Нужен, чтобы не выйти из ``async with async_playwright()`` — иначе Playwright
    сам завершит браузер при выходе из контекстного менеджера.
    """
    if worker_autoclose_browser_on_daemon_exit():
        return
    plat = (platform or worker_label.replace("_worker", "")).strip().lower()
    if page is not None and plat:
        await warm_playwright_page_home(page, plat)
    print(
        f"[{worker_label}] Ввод stdin завершён — Chromium не закрываем. "
        "Остановите worker вручную или задайте WORKER_AUTOCLOSE_BROWSER_ON_EXIT=1 "
        "для автозакрытия при выходе.",
        file=sys.stderr,
        flush=True,
    )
    await asyncio.Future()


async def cli_idle_keep_browser_open(worker_label: str) -> None:
    """После одноразового CLI: ответ уже в stdout, окно оставляем (см. ``worker_autoclose_browser_on_daemon_exit``)."""
    if worker_autoclose_browser_on_daemon_exit():
        return
    print(
        f"[{worker_label}] Ответ уже отправлен в stdout — Chromium не закрываем. "
        "Завершите процесс (Ctrl+C) или задайте WORKER_AUTOCLOSE_BROWSER_ON_EXIT=1.",
        file=sys.stderr,
        flush=True,
    )
    await asyncio.Future()


async def finish_cli_session_keep_browser_by_default(
    worker_label: str,
    context,
    browser,
) -> None:
    """Закрыть сессию только при ``WORKER_AUTOCLOSE_BROWSER_ON_EXIT=1``, иначе ждать с открытым окном."""
    if worker_autoclose_browser_on_daemon_exit():
        await close_context(context, browser)
    else:
        await cli_idle_keep_browser_open(worker_label)


async def wait_for_anti_bot_clear(
    page,
    *,
    platform: str,
    timeout_ms: int | None = None,
) -> None:
    """
    If a Cloudflare/anti-bot/captcha challenge is shown, wait until it is cleared.
    The browser stays open so the user can pass challenge manually.
    """
    plat = (platform or "").strip().lower()
    if timeout_ms is None:
        timeout_ms = anti_bot_wait_timeout_ms(plat)
    if plat == "tiktok":
        await recover_from_chromium_http_403(
            page,
            platform=plat,
            target_url=page.url if page.url and "tiktok.com" in page.url else None,
        )
    try:
        has_challenge = await page.evaluate(_CHALLENGE_JS)
    except Exception:
        has_challenge = False
    if not has_challenge:
        return

    captcha_msg = (
        f"[{plat}_worker] капча/антибот — пройдите проверку в открытом окне "
        f"(ожидание до {timeout_ms // 1000} с)…"
    )
    if plat == "tiktok":
        try:
            from platforms.tiktok.sadcaptcha import sadcaptcha_enabled

            if sadcaptcha_enabled():
                captcha_msg = (
                    f"[{plat}_worker] капча — SadCaptcha решает в фоне "
                    f"(ожидание до {timeout_ms // 1000} с)…"
                )
        except Exception:
            pass
    print(captcha_msg, file=sys.stderr, flush=True)

    use_sadcaptcha_api = False
    if plat == "tiktok":
        try:
            from platforms.tiktok.sadcaptcha import sadcaptcha_enabled

            use_sadcaptcha_api = sadcaptcha_enabled()
        except Exception:
            use_sadcaptcha_api = False

    if use_sadcaptcha_api:
        from platforms.tiktok.sadcaptcha import solve_tiktok_captcha_if_present

        deadline = time.monotonic() + timeout_ms / 1000.0
        while time.monotonic() < deadline:
            await solve_tiktok_captcha_if_present(page, force=True)
            try:
                still = await page.evaluate(_CHALLENGE_JS)
            except Exception:
                still = True
            if not still:
                await page.wait_for_timeout(2500)
                return
            await asyncio.sleep(4.0)
        raise ValueError(
            "TikTok: SadCaptcha не снял капчу за отведённое время. "
            "Проверьте баланс/ключ на sadcaptcha.com или увеличьте TIKTOK_CAPTCHA_WAIT_MS."
        )

    try:
        await page.wait_for_function(
            f"() => !({_CHALLENGE_JS})()",
            timeout=timeout_ms,
        )
        await page.wait_for_timeout(2500 if plat == "tiktok" else 1500)
    except Exception:
        if plat == "tiktok":
            raise ValueError(
                "TikTok: время ожидания капчи истекло. Пройдите проверку в открытом окне Chrome "
                "и повторите обновление (или увеличьте TIKTOK_CAPTCHA_WAIT_MS)."
            )
        raise ValueError(
            f"{platform.capitalize()} временно недоступен (антибот-челлендж), "
            "пройдите проверку в открывшемся окне и повторите обновление"
        )
