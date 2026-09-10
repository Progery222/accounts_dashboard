"""Канонизация YouTube username для хранения в Account.username."""
from __future__ import annotations

import re
from urllib.parse import unquote


_YT_CHANNEL_ID_RE = re.compile(r"^UC[\w-]{10,}$", re.I)


def canonical_youtube_username_for_storage(raw: str) -> str:
    """Хэндл или channel id — без превращения @кириллица в UC….

    Принимает полный URL (с https и без), /@name, /channel/UC…, /c/…, /user/….
    """
    s = (raw or "").strip()
    if not s:
        return s
    s = re.sub(r"^https?://", "", s, flags=re.I)
    s = re.sub(r"^(?:www\.)?(?:m\.)?(?:youtube\.com|youtu\.be)/", "", s, flags=re.I)
    s = s.split("?", 1)[0].split("#", 1)[0].strip("/")
    try:
        s = unquote(s)
    except Exception:
        pass
    parts = [p for p in s.split("/") if p]
    if not parts:
        return (raw or "").strip().lstrip("@")
    head = parts[0]
    low = head.lower()
    if low == "channel" and len(parts) > 1:
        return parts[1]
    if low in {"c", "user"} and len(parts) > 1:
        return parts[1].lstrip("@")
    if head.startswith("@"):
        return head[1:]
    return head.lstrip("@")


def is_youtube_channel_id(value: str) -> bool:
    return bool(_YT_CHANNEL_ID_RE.fullmatch((value or "").strip()))
