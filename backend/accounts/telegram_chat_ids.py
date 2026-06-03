"""Нормализация списка Telegram chat ID для отчётов автообновления."""
from __future__ import annotations

import re

_TELEGRAM_CHAT_ID_RE = re.compile(r"^-?\d{1,20}$")


def normalize_telegram_chat_ids(raw) -> list[str]:
    """
    Список chat_id (строки цифр, допускается минус для групп).
    Принимает list, одну строку, строку с разделителями , ; \\n.
    """
    if raw is None:
        return []
    if isinstance(raw, list):
        parts = raw
    elif isinstance(raw, str):
        s = raw.strip()
        if not s:
            return []
        parts = re.split(r"[\s,;]+", s) if re.search(r"[,;\s]", s) else [s]
    else:
        return []

    out: list[str] = []
    seen: set[str] = set()
    for item in parts:
        cid = str(item).strip()
        if not cid or not _TELEGRAM_CHAT_ID_RE.match(cid):
            continue
        if cid in seen:
            continue
        seen.add(cid)
        out.append(cid)
    return out


def telegram_chat_ids_from_config(config) -> list[str]:
    """Список из JSONField; fallback на устаревшее CharField."""
    ids = normalize_telegram_chat_ids(
        getattr(config, "auto_refresh_telegram_chat_ids", None),
    )
    if ids:
        return ids
    legacy = (getattr(config, "auto_refresh_telegram_chat_id", None) or "").strip()
    if legacy and _TELEGRAM_CHAT_ID_RE.match(legacy):
        return [legacy]
    return []
