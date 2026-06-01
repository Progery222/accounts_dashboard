"""TV broadcast emulation settings — shared JSON on the server (all browsers/devices)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_MAX_BYTES = 4 * 1024 * 1024


def _config_path() -> Path:
    try:
        from django.conf import settings as dj_settings

        base = Path(dj_settings.BASE_DIR)
    except Exception:
        base = Path(__file__).resolve().parents[1]
    return base / "config" / "tv_broadcast_emu.json"


def load_tv_emu_config() -> dict[str, Any] | None:
    path = _config_path()
    if not path.is_file():
        return None
    try:
        raw = path.read_text(encoding="utf-8")
        if not raw.strip():
            return None
        data = json.loads(raw)
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def save_tv_emu_config(config: dict[str, Any]) -> Path:
    if not isinstance(config, dict):
        raise ValueError("config должен быть объектом JSON")
    payload = json.dumps(config, ensure_ascii=False, separators=(",", ":"))
    if len(payload.encode("utf-8")) > _MAX_BYTES:
        raise ValueError("Конфигурация эмуляции слишком большая")
    path = _config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(payload, encoding="utf-8")
    tmp.replace(path)
    return path
