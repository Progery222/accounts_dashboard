"""Нормализация URL/label аккаунта для сопоставления с Links."""

from __future__ import annotations

import re
from urllib.parse import parse_qs, unquote, urlparse


def normalize_account_label(text: str | None) -> str | None:
    if text is None:
        return None
    s = str(text).strip()
    if not s:
        return None
    if not re.match(r"^https?://", s, re.I):
        s = s.lstrip("@").strip()
        return s.casefold() if s else None

    try:
        u = urlparse(s if "://" in s else f"https://{s}")
    except Exception:
        return s.casefold()

    host = (u.netloc or "").lower()
    if host.startswith("www."):
        host = host[4:]
    path = unquote(u.path or "").rstrip("/") or ""
    qs = parse_qs(u.query or "", keep_blank_values=True)

    if "tiktok.com" in host:
        m = re.search(r"@([^/?#]+)", path)
        if m:
            return f"tiktok:@{m.group(1).casefold()}"
        return f"{host}{path}".casefold()

    if "instagram.com" in host:
        segs = [p for p in path.split("/") if p]
        if segs:
            return f"instagram:{segs[0].casefold()}"
        return f"{host}{path}".casefold()

    if "youtube.com" in host or host == "youtu.be":
        if path.startswith("/@"):
            return f"youtube:{path[2:].split('/')[0].casefold()}"
        if path.startswith("/channel/"):
            return f"youtube:channel:{path.split('/')[2].casefold()}"
        return f"{host}{path}".casefold()

    if host in ("t.me", "telegram.me") or "telegram.org" in host:
        segs = [p for p in path.split("/") if p]
        if segs:
            return f"telegram:{segs[0].casefold()}"
        return f"{host}{path}".casefold()

    if host in ("x.com", "twitter.com"):
        segs = [p for p in path.split("/") if p]
        if segs:
            return f"x:{segs[0].casefold()}"
        return f"{host}{path}".casefold()

    if "threads.net" in host or "threads.com" in host:
        m = re.search(r"@([^/?#]+)", path)
        if m:
            return f"threads:@{m.group(1).casefold()}"
        return f"{host}{path}".casefold()

    if "facebook.com" in host or host == "fb.com":
        if "profile.php" in path.lower():
            ids = qs.get("id") or []
            if ids and re.fullmatch(r"\d{6,24}", str(ids[0]).strip()):
                return f"facebook:id:{ids[0].strip()}"
        segs = [p for p in path.split("/") if p]
        if segs and re.fullmatch(r"\d{6,24}", segs[0]):
            return f"facebook:id:{segs[0]}"
        if segs and not segs[0].lower().endswith(".php"):
            return f"facebook:{segs[0].casefold()}"
        return f"{host}{path}".casefold()

    if "rumble.com" in host:
        segs = [p for p in path.split("/") if p]
        if len(segs) >= 2 and segs[0].lower() == "c":
            return f"rumble:{segs[1].casefold()}"
        return f"{host}{path}".casefold()

    if "reddit.com" in host:
        segs = [p for p in path.split("/") if p]
        if segs and segs[0].lower() == "r" and len(segs) > 1:
            return f"reddit:{segs[1].casefold()}"
        return f"{host}{path}".casefold()

    return f"{host}{path}".casefold()


def platform_username_key(platform: str | None, username: str | None) -> str | None:
    p = str(platform or "").strip().casefold()
    u = str(username or "").strip().lstrip("@")
    if not p or not u:
        return None
    return f"{p}:{u.casefold()}"
