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


def _load_runtime_state() -> dict[str, int | bool]:
    path = _epoch_path()
    if not path.is_file():
        return {"runtime_epoch": 0, "runtime_paused": False}
    try:
        raw = path.read_text(encoding="utf-8")
        if not raw.strip():
            return {"runtime_epoch": 0, "runtime_paused": False}
        data = json.loads(raw)
    except (OSError, json.JSONDecodeError):
        return {"runtime_epoch": 0, "runtime_paused": False}
    if not isinstance(data, dict):
        return {"runtime_epoch": 0, "runtime_paused": False}
    try:
        epoch = max(0, int(data.get("runtime_epoch", 0)))
    except (TypeError, ValueError):
        epoch = 0
    paused = bool(data.get("runtime_paused", False))
    return {"runtime_epoch": epoch, "runtime_paused": paused}


def _save_runtime_state(state: dict[str, int | bool]) -> None:
    path = _epoch_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(
        {
            "runtime_epoch": max(0, int(state.get("runtime_epoch", 0))),
            "runtime_paused": bool(state.get("runtime_paused", False)),
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(payload, encoding="utf-8")
    tmp.replace(path)


def load_tv_emu_runtime_epoch() -> int:
    return int(_load_runtime_state()["runtime_epoch"])


def load_tv_emu_runtime_paused() -> bool:
    return bool(_load_runtime_state()["runtime_paused"])


def set_tv_emu_runtime_paused(paused: bool) -> bool:
    state = _load_runtime_state()
    state["runtime_paused"] = bool(paused)
    _save_runtime_state(state)
    return bool(state["runtime_paused"])


def bump_tv_emu_runtime_epoch() -> int:
    state = _load_runtime_state()
    state["runtime_epoch"] = int(state["runtime_epoch"]) + 1
    state["runtime_paused"] = False
    _save_runtime_state(state)
    return int(state["runtime_epoch"])
