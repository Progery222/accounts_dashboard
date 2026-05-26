"""
Параметры браузера Facebook (UA, viewport, locale, stealth).

Хранятся в backend/config/facebook_browser_profile.json; env FACEBOOK_* перекрывает файл.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/145.0.7632.6 Safari/537.36"
)
DEFAULT_VIEWPORT_WIDTH = 1366
DEFAULT_VIEWPORT_HEIGHT = 900
DEFAULT_LOCALE = "ru-RU"
DEFAULT_LANGUAGES = ["ru-RU", "ru", "en-US", "en"]


def _config_path() -> Path:
    try:
        from django.conf import settings as dj_settings

        base = Path(dj_settings.BASE_DIR)
    except Exception:
        base = Path(__file__).resolve().parents[2]
    return base / "config" / "facebook_browser_profile.json"


def default_profile() -> dict[str, Any]:
    return {
        "user_agent": DEFAULT_USER_AGENT,
        "viewport_width": DEFAULT_VIEWPORT_WIDTH,
        "viewport_height": DEFAULT_VIEWPORT_HEIGHT,
        "locale": DEFAULT_LOCALE,
        "languages": list(DEFAULT_LANGUAGES),
        "stealth_enabled": True,
        "hide_automation_flags": True,
    }


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
    ua = (os.environ.get("FACEBOOK_USER_AGENT") or "").strip()
    if ua:
        out["user_agent"] = ua
    for key, env_name, cast in (
        ("viewport_width", "FACEBOOK_VIEWPORT_WIDTH", int),
        ("viewport_height", "FACEBOOK_VIEWPORT_HEIGHT", int),
    ):
        raw = (os.environ.get(env_name) or "").strip()
        if raw:
            try:
                out[key] = cast(raw)
            except ValueError:
                pass
    loc = (os.environ.get("FACEBOOK_LOCALE") or "").strip()
    if loc:
        out["locale"] = loc
    langs = (os.environ.get("FACEBOOK_LANGUAGES") or "").strip()
    if langs:
        out["languages"] = _parse_languages(langs)
    for key, env_name in (
        ("stealth_enabled", "FACEBOOK_STEALTH_ENABLED"),
        ("hide_automation_flags", "FACEBOOK_HIDE_AUTOMATION_FLAGS"),
    ):
        raw = (os.environ.get(env_name) or "").strip().lower()
        if raw in {"1", "true", "yes", "on", "y"}:
            out[key] = True
        elif raw in {"0", "false", "no", "off", "n"}:
            out[key] = False
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
    return data


def normalize_patch(payload: dict) -> dict[str, Any]:
    cur = load_profile()
    if not isinstance(payload, dict):
        raise ValueError("Ожидается JSON-объект")
    if payload.get("reset_defaults"):
        return default_profile()
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
            raise ValueError("Некорректный locale (например ru-RU или en-US)")
        cur["locale"] = loc
    if "languages" in payload:
        cur["languages"] = _parse_languages(payload["languages"])
    if "stealth_enabled" in payload:
        cur["stealth_enabled"] = bool(payload["stealth_enabled"])
    if "hide_automation_flags" in payload:
        cur["hide_automation_flags"] = bool(payload["hide_automation_flags"])
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
    }
    path.write_text(json.dumps(to_store, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    _apply_to_environ(to_store)
    return path


def _apply_to_environ(data: dict[str, Any]) -> None:
    os.environ["FACEBOOK_USER_AGENT"] = str(data["user_agent"])
    os.environ["FACEBOOK_VIEWPORT_WIDTH"] = str(data["viewport_width"])
    os.environ["FACEBOOK_VIEWPORT_HEIGHT"] = str(data["viewport_height"])
    os.environ["FACEBOOK_LOCALE"] = str(data["locale"])
    os.environ["FACEBOOK_LANGUAGES"] = ",".join(_parse_languages(data.get("languages")))
    os.environ["FACEBOOK_STEALTH_ENABLED"] = "true" if data.get("stealth_enabled") else "false"
    os.environ["FACEBOOK_HIDE_AUTOMATION_FLAGS"] = (
        "true" if data.get("hide_automation_flags") else "false"
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


def launch_args(profile: dict[str, Any] | None = None, *, channel: str | None = None) -> list[str]:
    from platforms.worker_utils import chromium_launch_args

    p = profile or load_profile()
    return chromium_launch_args(
        channel=channel,
        hide_automation=bool(p.get("hide_automation_flags", True)),
    )


def context_options(profile: dict[str, Any] | None = None) -> dict[str, Any]:
    p = profile or load_profile()
    return {
        "locale": p["locale"],
        "viewport": {"width": p["viewport_width"], "height": p["viewport_height"]},
        "user_agent": p["user_agent"],
    }


def profile_for_api() -> dict[str, Any]:
    p = load_profile()
    return {
        **p,
        "languages": _parse_languages(p.get("languages")),
        "config_path": str(_config_path()),
        "defaults": default_profile(),
    }
