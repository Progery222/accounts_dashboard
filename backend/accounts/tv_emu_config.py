"""TV broadcast emulation settings — shared JSON on the server (all browsers/devices)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_MAX_BYTES = 4 * 1024 * 1024


def _base_dir() -> Path:
    try:
        from django.conf import settings as dj_settings

        return Path(dj_settings.BASE_DIR)
    except Exception:
        return Path(__file__).resolve().parents[1]


def _config_path() -> Path:
    return _base_dir() / "config" / "tv_broadcast_emu.json"


def _epoch_path() -> Path:
    return _base_dir() / "config" / "tv_broadcast_emu_epoch.json"


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


def load_tv_emu_runtime_epoch() -> int:
    path = _epoch_path()
    if not path.is_file():
        return 0
    try:
        raw = path.read_text(encoding="utf-8")
        if not raw.strip():
            return 0
        data = json.loads(raw)
    except (OSError, json.JSONDecodeError):
        return 0
    if not isinstance(data, dict):
        return 0
    try:
        return max(0, int(data.get("runtime_epoch", 0)))
    except (TypeError, ValueError):
        return 0


def bump_tv_emu_runtime_epoch() -> int:
    path = _epoch_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    next_epoch = load_tv_emu_runtime_epoch() + 1
    payload = json.dumps({"runtime_epoch": next_epoch}, ensure_ascii=False, separators=(",", ":"))
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(payload, encoding="utf-8")
    tmp.replace(path)
    return next_epoch
