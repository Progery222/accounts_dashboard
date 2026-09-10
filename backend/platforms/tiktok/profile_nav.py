"""Навигация на профиль TikTok с восстановлением после редиректа на ленту."""
from __future__ import annotations

import asyncio
import re
import sys
import time


def _norm_user(u: str) -> str:
    return (u or "").strip().lstrip("@").lower()


def _tiktok_profile_url_regex(owner: str) -> re.Pattern[str]:
    """URL страницы нужного @handle (/@user, /@user/video/…); не главная и не лента."""
    o = re.escape(_norm_user(owner))
    return re.compile(
        rf"https?://(?:[\w.-]+\.)?tiktok\.com/@{o}(?:/|$|\?)",
        re.IGNORECASE,
    )


async def _wait_tiktok_on_profile_url(page, owner: str, *, timeout_ms: int = 30_000) -> bool:
    """Ждём, пока адресная строка — профиль нужного @handle (не главная, не чужой аккаунт)."""
    pat = _tiktok_profile_url_regex(owner)
    deadline = time.monotonic() + timeout_ms / 1000.0
    while time.monotonic() < deadline:
        cur = (page.url or "").split("#")[0]
        if pat.search(cur):
            return True
        await asyncio.sleep(0.2)
    print(
        f"[tiktok] ожидался профиль @{owner}, сейчас url={page.url!r}",
        file=sys.stderr,
    )
    return False


async def _tiktok_goto_profile_with_redirect_recovery(
    page,
    owner_username: str,
    target_url: str,
    _wu,
    *,
    rounds: int = 5,
    dwell_s: float = 11.0,
) -> bool:
    """
    Переход на URL профиля (обычно https://www.tiktok.com/@handle). TikTok часто после загрузки
    уводит залогиненную сессию на /for_you или на голый tiktok.com — повторяем goto
    и ждём, пока в адресной строке снова будет нужный @handle.
    """
    owner_username = _norm_user(owner_username)
    target_url = (target_url or "").strip().split("#")[0]
    if not target_url:
        return False
    pat = _tiktok_profile_url_regex(owner_username)
    for r in range(rounds):
        if _wu is not None and hasattr(_wu, "tiktok_goto_with_403_recovery"):
            await _wu.tiktok_goto_with_403_recovery(page, target_url, timeout_ms=45_000)
        else:
            await page.goto(target_url, wait_until="domcontentloaded", timeout=45_000)
        if _wu is not None and hasattr(_wu, "wait_for_anti_bot_clear"):
            await _wu.wait_for_anti_bot_clear(page, platform="tiktok")
        deadline = time.monotonic() + dwell_s
        while time.monotonic() < deadline:
            cur = (page.url or "").split("#")[0]
            if pat.search(cur):
                return True
            cur_l = cur.lower()
            # Не сидим на ленте / главной до конца dwell — сразу следующий goto.
            if (
                "foryou" in cur_l
                or "for_you" in cur_l
                or re.search(r"tiktok\.com/?(?:\?|$)", cur_l)
            ):
                break
            await asyncio.sleep(0.2)
        print(
            f"[tiktok] после goto остаёмся вне профиля @{owner_username}, "
            f"url={page.url!r} (раунд {r + 1}/{rounds})",
            file=sys.stderr,
        )
    return bool(pat.search((page.url or "").split("#")[0]))
