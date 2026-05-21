"""Валидация display_name и avatar_url при съёме Facebook (ложные срабатывания UI)."""
from __future__ import annotations

import re

_JUNK_DISPLAY_RE = re.compile(
    r"уведомлен|notification|поиск|search|меню|menu|^photo$",
    re.IGNORECASE,
)


def is_junk_facebook_display_name(name: str | None) -> bool:
    s = (name or "").strip()
    if not s or len(s) > 120:
        return True
    if s.isdigit():
        return True
    return bool(_JUNK_DISPLAY_RE.search(s))


def sanitize_facebook_display_name(name: str | None, *, fallback: str = "") -> str:
    s = (name or "").strip()
    if is_junk_facebook_display_name(s):
        return fallback
    return s


def is_usable_facebook_avatar_url(url: str | None) -> bool:
    u = (url or "").strip()
    if not u:
        return False
    if "emoji.php" in u.lower():
        return False
    if "scontent" not in u and "fbcdn" not in u:
        return False
    if any(x in u for x in ("/p16x16/", "/p32x32/", "/p40x40/", "/p48x48/")):
        return False
    return True
