"""Канонический URL профиля аккаунта дашборда (для сопоставления с label в Links)."""

from __future__ import annotations

import re
from urllib.parse import quote, urlparse

from accounts.models import Account, Platform


def account_profile_url(account: Account) -> str | None:
    platform = str(account.platform or "")
    username = str(account.username or "").strip().lstrip("@")
    if not username:
        return None
    if platform == Platform.TIKTOK:
        return f"https://www.tiktok.com/@{quote(username, safe='')}"
    if platform == Platform.INSTAGRAM:
        return f"https://www.instagram.com/{quote(username, safe='')}/"
    if platform == Platform.YOUTUBE:
        if re.fullmatch(r"UC[\w-]{10,}", username, re.I):
            return f"https://www.youtube.com/channel/{quote(username, safe='')}"
        return f"https://www.youtube.com/@{quote(username, safe='')}"
    if platform == Platform.TELEGRAM:
        return f"https://t.me/{quote(username, safe='')}"
    if platform == Platform.X:
        return f"https://x.com/{quote(username, safe='')}"
    if platform == Platform.THREADS:
        return f"https://www.threads.net/@{quote(username, safe='')}"
    if platform == Platform.FACEBOOK:
        return _facebook_profile_url_from_username_field(username)
    if platform == Platform.RUMBLE:
        return f"https://rumble.com/c/{quote(username, safe='')}"
    if platform == Platform.REDDIT:
        return f"https://www.reddit.com/r/{quote(username, safe='')}/"
    return None


def _facebook_profile_url_from_username_field(raw: str) -> str | None:
    s = raw.strip().lstrip("@")
    if not s:
        return None
    if re.match(r"^https?://", s, re.I):
        try:
            url = urlparse(s)
            host = (url.netloc or "").lower()
            if not (
                host.endswith("facebook.com")
                or host == "fb.com"
                or host.endswith(".facebook.com")
            ):
                return None
            path = (url.path or "").rstrip("/")
            id_m = re.search(r"\bid=(\d+)", url.query or "", re.I)
            if "profile.php" in path.lower() and id_m:
                return f"https://www.facebook.com/profile.php?id={id_m.group(1)}"
            segs = [p for p in path.split("/") if p]
            if segs and re.fullmatch(r"\d{6,24}", segs[0]):
                return f"https://www.facebook.com/profile.php?id={segs[0]}"
            if segs and not segs[0].lower().endswith(".php"):
                return f"https://www.facebook.com/{segs[0]}"
            return f"https://{host}{path or '/'}"
        except Exception:
            return None
    if re.search(r"profile\.php", s, re.I) and re.search(r"\bid=\d+", s, re.I):
        m = re.search(r"\bid=(\d+)", s, re.I)
        if m:
            return f"https://www.facebook.com/profile.php?id={m.group(1)}"
    if re.fullmatch(r"\d{6,24}", s):
        return f"https://www.facebook.com/profile.php?id={s}"
    return f"https://www.facebook.com/{quote(s, safe='')}"
