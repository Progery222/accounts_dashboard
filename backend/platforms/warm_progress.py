"""JSON-файл прогресса прогрева (worker пишет, Django читает для UI)."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any


def write_warm_progress(path: Path | str, **fields: Any) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    data: dict[str, Any] = {}
    if p.exists():
        try:
            raw = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                data = raw
        except Exception:
            pass
    data.update(fields)
    data["updated_at"] = time.time()
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    tmp.replace(p)


def read_warm_progress(path: Path | str) -> dict[str, Any]:
    p = Path(path)
    if not p.exists():
        return {}
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {}
    except Exception:
        return {}


def warm_cancel_requested(progress_path: Path | str | None) -> bool:
    if not progress_path:
        return False
    return bool(read_warm_progress(progress_path).get("cancel_requested"))
