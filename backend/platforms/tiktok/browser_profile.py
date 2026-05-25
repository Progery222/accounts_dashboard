"""
Параметры «отпечатка» браузера TikTok (UA, viewport, locale, stealth).

Хранятся в backend/config/tiktok_browser_profile.json; env TIKTOK_* перекрывает файл.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

# Дефолты совпадают с platforms/worker_utils.py
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/145.0.7632.6 Safari/537.36"
)
DEFAULT_VIEWPORT_WIDTH = 1280
DEFAULT_VIEWPORT_HEIGHT = 900
DEFAULT_LOCALE = "en-US"
DEFAULT_LANGUAGES = ["en-US", "en"]

# Два изолированных user-data-dir Chrome (не общий launch + storage_state).
REFRESH_BROWSER_AUTHORIZED = "authorized"
REFRESH_BROWSER_SECONDARY = "secondary"
REFRESH_BROWSER_SLOTS = (REFRESH_BROWSER_AUTHORIZED, REFRESH_BROWSER_SECONDARY)
DIR_AUTHORIZED = "tiktok_chrome_authorized"
DIR_SECONDARY = "tiktok_chrome_secondary"
STATE_AUTHORIZED = "tiktok_state.json"
STATE_SECONDARY = "tiktok_state_secondary.json"


def _config_path() -> Path:
    try:
        from django.conf import settings as dj_settings

        base = Path(dj_settings.BASE_DIR)
    except Exception:
        base = Path(__file__).resolve().parents[2]
    return base / "config" / "tiktok_browser_profile.json"


def default_profile() -> dict[str, Any]:
    return {
        "user_agent": DEFAULT_USER_AGENT,
        "viewport_width": DEFAULT_VIEWPORT_WIDTH,
        "viewport_height": DEFAULT_VIEWPORT_HEIGHT,
        "locale": DEFAULT_LOCALE,
        "languages": list(DEFAULT_LANGUAGES),
        "stealth_enabled": True,
        "hide_automation_flags": True,
        "refresh_browser_slot": REFRESH_BROWSER_AUTHORIZED,
    }


def profile_base_dir() -> Path:
    """Каталог ACCOUNTS_BROWSER_PROFILE_DIR / TikStatsChromeProfile."""
    env = (os.environ.get("BROWSER_PROFILE_DIR") or "").strip()
    if env:
        return Path(env)
    try:
        from platforms.worker_utils import default_profile_dir

        return default_profile_dir()
    except Exception:
        home = Path.home()
        if (home / "AppData").exists():
            return home / "AppData" / "Local" / "TikStatsChromeProfile"
        return home / ".config" / "tikstats-chrome-profile"


def normalize_refresh_browser_slot(raw: Any) -> str:
    v = str(raw or REFRESH_BROWSER_AUTHORIZED).strip().lower()
    if v in {REFRESH_BROWSER_SECONDARY, "guest", "secondary", "no_auth", "alt"}:
        return REFRESH_BROWSER_SECONDARY
    return REFRESH_BROWSER_AUTHORIZED


def user_data_dir_for_slot(profile_base: Path | None, slot: str) -> Path:
    base = profile_base or profile_base_dir()
    if normalize_refresh_browser_slot(slot) == REFRESH_BROWSER_SECONDARY:
        return base / DIR_SECONDARY
    return base / DIR_AUTHORIZED


def state_file_for_slot(profile_base: Path | None, slot: str) -> Path:
    base = profile_base or profile_base_dir()
    if normalize_refresh_browser_slot(slot) == REFRESH_BROWSER_SECONDARY:
        return base / STATE_SECONDARY
    return base / STATE_AUTHORIZED


def browser_slots_for_api(profile_base: Path | None = None) -> list[dict[str, Any]]:
    base = profile_base or profile_base_dir()
    auth_dir = user_data_dir_for_slot(base, REFRESH_BROWSER_AUTHORIZED)
    sec_dir = user_data_dir_for_slot(base, REFRESH_BROWSER_SECONDARY)
    auth_state = state_file_for_slot(base, REFRESH_BROWSER_AUTHORIZED)
    sec_state = state_file_for_slot(base, REFRESH_BROWSER_SECONDARY)
    return [
        {
            "id": REFRESH_BROWSER_AUTHORIZED,
            "label": "Chrome с авторизацией",
            "user_data_dir": str(auth_dir),
            "state_file": str(auth_state),
            "state_exists": auth_state.is_file(),
            "hint": "Куки из tiktok_state.json подмешиваются при старте воркера.",
        },
        {
            "id": REFRESH_BROWSER_SECONDARY,
            "label": "Отдельный Chrome без авторизации",
            "user_data_dir": str(sec_dir),
            "state_file": str(sec_state),
            "state_exists": sec_state.is_file(),
            "hint": "Изолированный профиль; при необходимости войдите вручную в этом окне.",
        },
    ]


def _parse_languages(raw: Any) -> list[str]:
    if isinstance(raw, list):
        out = [str(x).strip() for x in raw if str(x).strip()]
        return out or list(DEFAULT_LANGUAGES)
    s = str(raw or "").strip()
    if not s:
        return list(DEFAULT_LANGUAGES)
    if s.startswith("["):
        try:
            data = json.loads(s)
            if isinstance(data, list):
                return _parse_languages(data)
        except Exception:
            pass
    return [p.strip() for p in s.split(",") if p.strip()] or list(DEFAULT_LANGUAGES)


def _env_overrides() -> dict[str, Any]:
    out: dict[str, Any] = {}
    ua = (os.environ.get("TIKTOK_USER_AGENT") or "").strip()
    if ua:
        out["user_agent"] = ua
    for key, env_name, cast in (
        ("viewport_width", "TIKTOK_VIEWPORT_WIDTH", int),
        ("viewport_height", "TIKTOK_VIEWPORT_HEIGHT", int),
    ):
        raw = (os.environ.get(env_name) or "").strip()
        if raw:
            try:
                out[key] = cast(raw)
            except ValueError:
                pass
    loc = (os.environ.get("TIKTOK_LOCALE") or "").strip()
    if loc:
        out["locale"] = loc
    langs = (os.environ.get("TIKTOK_LANGUAGES") or "").strip()
    if langs:
        out["languages"] = _parse_languages(langs)
    for key, env_name in (
        ("stealth_enabled", "TIKTOK_STEALTH_ENABLED"),
        ("hide_automation_flags", "TIKTOK_HIDE_AUTOMATION_FLAGS"),
    ):
        raw = (os.environ.get(env_name) or "").strip().lower()
        if raw in {"1", "true", "yes", "on", "y"}:
            out[key] = True
        elif raw in {"0", "false", "no", "off", "n"}:
            out[key] = False
    raw_slot = (os.environ.get("TIKTOK_REFRESH_BROWSER_SLOT") or "").strip()
    if raw_slot:
        out["refresh_browser_slot"] = normalize_refresh_browser_slot(raw_slot)
    return out


def load_profile() -> dict[str, Any]:
    data = default_profile()
    path = _config_path()
    if path.is_file():
        try:
            stored = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(stored, dict):
                data.update(stored)
        except Exception:
            pass
    data.update(_env_overrides())
    data["languages"] = _parse_languages(data.get("languages"))
    data["viewport_width"] = max(320, min(7680, int(data.get("viewport_width") or DEFAULT_VIEWPORT_WIDTH)))
    data["viewport_height"] = max(240, min(4320, int(data.get("viewport_height") or DEFAULT_VIEWPORT_HEIGHT)))
    data["locale"] = str(data.get("locale") or DEFAULT_LOCALE).strip() or DEFAULT_LOCALE
    data["user_agent"] = str(data.get("user_agent") or DEFAULT_USER_AGENT).strip() or DEFAULT_USER_AGENT
    data["stealth_enabled"] = bool(data.get("stealth_enabled", True))
    data["hide_automation_flags"] = bool(data.get("hide_automation_flags", True))
    data["refresh_browser_slot"] = normalize_refresh_browser_slot(
        data.get("refresh_browser_slot"),
    )
    return data


def normalize_patch(payload: dict) -> dict[str, Any]:
    """Валидация тела запроса из UI."""
    cur = load_profile()
    if not isinstance(payload, dict):
        raise ValueError("Ожидается JSON-объект")
    if "user_agent" in payload:
        ua = str(payload["user_agent"] or "").strip()
        if len(ua) < 20 or len(ua) > 512:
            raise ValueError("User-Agent: от 20 до 512 символов")
        cur["user_agent"] = ua
    if "viewport_width" in payload:
        w = int(payload["viewport_width"])
        if w < 320 or w > 7680:
            raise ValueError("Ширина окна: 320–7680")
        cur["viewport_width"] = w
    if "viewport_height" in payload:
        h = int(payload["viewport_height"])
        if h < 240 or h > 4320:
            raise ValueError("Высота окна: 240–4320")
        cur["viewport_height"] = h
    if "locale" in payload:
        loc = str(payload["locale"] or "").strip()
        if not loc or len(loc) > 16:
            raise ValueError("Некорректный locale (например en-US или ru-RU)")
        cur["locale"] = loc
    if "languages" in payload:
        cur["languages"] = _parse_languages(payload["languages"])
    if "stealth_enabled" in payload:
        cur["stealth_enabled"] = bool(payload["stealth_enabled"])
    if "hide_automation_flags" in payload:
        cur["hide_automation_flags"] = bool(payload["hide_automation_flags"])
    if "refresh_browser_slot" in payload:
        cur["refresh_browser_slot"] = normalize_refresh_browser_slot(
            payload["refresh_browser_slot"],
        )
    if payload.get("reset_defaults"):
        cur = default_profile()
    return cur


def save_profile(data: dict[str, Any]) -> Path:
    path = _config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    to_store = {
        "user_agent": data["user_agent"],
        "viewport_width": data["viewport_width"],
        "viewport_height": data["viewport_height"],
        "locale": data["locale"],
        "languages": _parse_languages(data.get("languages")),
        "stealth_enabled": bool(data.get("stealth_enabled", True)),
        "hide_automation_flags": bool(data.get("hide_automation_flags", True)),
        "refresh_browser_slot": normalize_refresh_browser_slot(
            data.get("refresh_browser_slot"),
        ),
    }
    path.write_text(json.dumps(to_store, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    _apply_to_environ(to_store)
    return path


def _apply_to_environ(data: dict[str, Any]) -> None:
    os.environ["TIKTOK_USER_AGENT"] = str(data["user_agent"])
    os.environ["TIKTOK_VIEWPORT_WIDTH"] = str(data["viewport_width"])
    os.environ["TIKTOK_VIEWPORT_HEIGHT"] = str(data["viewport_height"])
    os.environ["TIKTOK_LOCALE"] = str(data["locale"])
    os.environ["TIKTOK_LANGUAGES"] = ",".join(_parse_languages(data.get("languages")))
    os.environ["TIKTOK_STEALTH_ENABLED"] = "true" if data.get("stealth_enabled") else "false"
    os.environ["TIKTOK_HIDE_AUTOMATION_FLAGS"] = (
        "true" if data.get("hide_automation_flags") else "false"
    )
    os.environ["TIKTOK_REFRESH_BROWSER_SLOT"] = normalize_refresh_browser_slot(
        data.get("refresh_browser_slot"),
    )


def build_stealth_script(languages: list[str]) -> str:
    langs = languages or list(DEFAULT_LANGUAGES)
    langs_js = json.dumps(langs, ensure_ascii=False)
    return f"""
    (() => {{
        Object.defineProperty(navigator, 'webdriver', {{ get: () => undefined }});
        if (!window.chrome) {{
            window.chrome = {{ runtime: {{}}, loadTimes: function(){{}}, csi: function(){{}}, app: {{}} }};
        }}
        Object.defineProperty(navigator, 'plugins', {{
            get: () => {{ const p = [1,2,3,4,5]; p.item = () => null; p.namedItem = () => null; p.refresh = () => null; return p; }}
        }});
        Object.defineProperty(navigator, 'languages', {{ get: () => {langs_js} }});
    }})();
"""


def launch_args(profile: dict[str, Any] | None = None) -> list[str]:
    p = profile or load_profile()
    args: list[str] = []
    if p.get("hide_automation_flags", True):
        args.append("--disable-blink-features=AutomationControlled")
    return args


def context_options(profile: dict[str, Any] | None = None) -> dict[str, Any]:
    p = profile or load_profile()
    return {
        "locale": p["locale"],
        "viewport": {"width": p["viewport_width"], "height": p["viewport_height"]},
        "user_agent": p["user_agent"],
    }


def profile_for_api() -> dict[str, Any]:
    p = load_profile()
    base = profile_base_dir()
    slot = normalize_refresh_browser_slot(p.get("refresh_browser_slot"))
    return {
        **p,
        "languages": _parse_languages(p.get("languages")),
        "config_path": str(_config_path()),
        "defaults": default_profile(),
        "refresh_browser_slot": slot,
        "browser_slots": browser_slots_for_api(base),
        "active_user_data_dir": str(user_data_dir_for_slot(base, slot)),
    }
