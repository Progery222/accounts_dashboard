"""Сохранение куков Instagram в Playwright storage state (instagram_state.json)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def cookies_dict_to_playwright_list(cookies: dict[str, str]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for name, value in cookies.items():
        if not name or not value:
            continue
        out.append(
            {
                "name": name,
                "value": value,
                "domain": ".instagram.com",
                "path": "/",
                "secure": True,
                "sameSite": "Lax",
            }
        )
    return out


def write_instagram_storage_state(cookies: dict[str, str], path: Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"cookies": cookies_dict_to_playwright_list(cookies), "origins": []}
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path
