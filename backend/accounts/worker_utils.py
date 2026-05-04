"""
Legacy-копия воркер-утилит для скриптов в backend/accounts/*_worker.py и
tiktok_app/playwright_worker.py. Единый источник правды — platforms/worker_utils.py;
эта копия должна оставаться API-совместимой (см. resolve_headless / launch_context).
"""
import json
import os
import shutil
import sys
from pathlib import Path


# ── Paths ──────────────────────────────────────────────────────────────────────

def default_profile_dir() -> Path:
    env = (os.environ.get("BROWSER_PROFILE_DIR") or "").strip()
    if env:
        return Path(env)
    home = Path.home()
    if (home / "AppData").exists():          # Windows
        return home / "AppData" / "Local" / "TikStatsChromeProfile"
    return home / ".config" / "tikstats-chrome-profile"   # Linux / macOS


def state_file_path(platform: str, profile_dir: Path | None = None) -> Path:
    """Return the per-platform storage-state JSON path."""
    base = profile_dir or default_profile_dir()
    return base / f"{platform}_state.json"


def _storage_state_has_instagram_session(path: Path) -> bool:
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

_COMMON_ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--disable-features=AutomationControlled",
    "--no-first-run",
    "--no-default-browser-check",
    "--disable-default-apps",
]


_TRUE_VALUES = frozenset({"1", "true", "yes", "on", "y"})
_FALSE_VALUES = frozenset({"0", "false", "no", "off", "n"})


def _env_bool(name: str) -> bool | None:
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
    return None


def resolve_headless(*, platform: str | None = None, fallback: bool = False) -> bool:
    """См. platforms/worker_utils.resolve_headless."""
    if platform:
        per_platform = _env_bool(f"{platform.upper()}_HEADLESS")
        if per_platform is not None:
            return per_platform
    glob = _env_bool("BROWSER_HEADLESS")
    if glob is not None:
        return glob
    return fallback

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


async def launch_context(
    pw,
    *,
    platform: str,
    profile_dir: Path | None = None,
    headless: bool | None = None,
    locale: str = "en-US",
    viewport: dict | None = None,
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

    base = profile_dir or default_profile_dir()
    sf = state_file_path(platform, base)

    ig_state_broken = (
        platform == "instagram"
        and sf.exists()
        and not _storage_state_has_instagram_session(sf)
    )
    if ig_state_broken:
        print(
            f"[{platform}_worker] {sf.name} без sessionid Instagram — игнорирую, "
            "беру persistent profile.",
            file=sys.stderr,
        )

    use_storage_state = sf.exists() and not ig_state_broken

    if use_storage_state:
        print(f"[{platform}_worker] loading state from {sf.name}", file=sys.stderr)
        browser = await pw.chromium.launch(
            headless=headless,
            args=_COMMON_ARGS,
        )
        context = await browser.new_context(
            storage_state=str(sf),
            locale=locale,
            viewport=viewport,
            user_agent=_UA_CHROME,
        )
        await context.add_init_script(_STEALTH_SCRIPT)
        return context, browser   # caller must close browser too

    # ── Fallback: persistent profile ──────────────────────────────────────────
    print(
        f"[{platform}_worker] using persistent profile "
        f"(import cookies via Settings to protect other sessions)",
        file=sys.stderr,
    )
    base.mkdir(parents=True, exist_ok=True)
    for attempt in range(2):
        try:
            context = await pw.chromium.launch_persistent_context(
                str(base),
                headless=headless,
                args=_COMMON_ARGS,
                locale=locale,
                viewport=viewport,
            )
            await context.add_init_script(_STEALTH_SCRIPT)
            return context, None   # caller closes context only
        except Exception as exc:
            if attempt == 0:
                print(
                    f"[{platform}_worker] launch failed ({exc}); "
                    "cleaning Chrome artefacts and retrying…",
                    file=sys.stderr,
                )
                cleanup_chrome_artifacts(base)
            else:
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
