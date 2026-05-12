"""
Карточка профиля подписчика Instagram по HTTP (без Playwright).

Куки и User-Agent берутся из активной страницы Playwright после съёма списка в модалке,
чтобы запросы шли в той же «залогиненной» сессии, что и браузер worker.

Посты подписчика здесь не запрашиваются — только общие поля (имя, аватар, био, счётчики,
признак закрытого профиля). Таймаут задаётся на каждый GET.
"""
from __future__ import annotations

import html as html_module
import re
import sys
from typing import Any

import httpx

from platforms.instagram.audience_followers_modal import norm_ig_username


def _html_unescape(s: str) -> str:
    if not s:
        return ""
    t = html_module.unescape(s)
    return t.replace("&quot;", '"').replace("&#39;", "'")


def parse_instagram_profile_html(html: str) -> dict[str, Any]:
    """
    Разбор публичного HTML профиля (фрагменты JSON + og-теги).
    Возвращает словарь полей; _ok — удалось ли извлечь хоть что-то полезное.
    """
    out: dict[str, Any] = {
        "display_name": "",
        "avatar_url": "",
        "bio": "",
        "follower_count": 0,
        "following_count": 0,
        "like_count": 0,
        "is_private": False,
        "_ok": False,
    }
    if not html or len(html) < 400:
        return out

    low = html.lower()
    if "accounts/login" in low and "password" in low and "username" in low:
        out["_auth_required"] = True
        return out

    if re.search(r'"is_private"\s*:\s*true\b', html):
        out["is_private"] = True

    m = re.search(r'"edge_followed_by"\s*:\s*\{\s*"count"\s*:\s*(\d+)', html)
    if m:
        out["follower_count"] = max(0, int(m.group(1)))
    m = re.search(r'"edge_follow"\s*:\s*\{\s*"count"\s*:\s*(\d+)', html)
    if m:
        out["following_count"] = max(0, int(m.group(1)))

    m = re.search(
        r'<meta\s+property="og:title"\s+content="([^"]*)"',
        html,
        re.I,
    )
    if m:
        t = _html_unescape(m.group(1)).strip()
        lp = t.find("(")
        if lp > 0:
            t = t[:lp].strip()
        else:
            t = t.split("•")[0].strip()
        out["display_name"] = t[:255]

    m = re.search(r'<meta\s+property="og:image"\s+content="([^"]*)"', html, re.I)
    if m:
        out["avatar_url"] = _html_unescape(m.group(1)).strip()[:2048]

    m = re.search(r'<meta\s+name="description"\s+content="([^"]*)"', html, re.I)
    if m:
        c = _html_unescape(m.group(1)).strip()
        if " - see instagram" in c.lower():
            c = ""
        else:
            on_idx = re.search(r"\s+on\s+Instagram:", c, re.I)
            if on_idx:
                c = c[: on_idx.start()].strip()
            lead_re = re.compile(
                r"^[\d.,\s]+\s*posts?\s*[-–,]\s*[\d.,\s]+\s*followers?\s*[-–,]\s*[\d.,\s]+\s+following\s*[-–]\s*",
                re.I,
            )
            c = lead_re.sub("", c).strip()
            mc = re.match(r"^([^:]{1,80}):\s*([\s\S]+)$", c)
            if mc and mc.group(2):
                if not out["display_name"]:
                    out["display_name"] = mc.group(1).strip()[:255]
                c = mc.group(2).strip()
            out["bio"] = c[:4000]

    blob = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html)).lower()
    priv_phrases = (
        "this account is private",
        "this profile is private",
        "this user's profile is private",
        "follow to see their photos and videos",
        "закрытый профиль",
        "закрытый аккаунт",
        "этот аккаунт закрыт",
    )
    if any(p in blob for p in priv_phrases):
        out["is_private"] = True

    out["_ok"] = bool(
        out.get("avatar_url")
        or out.get("display_name")
        or int(out.get("follower_count") or 0) > 0
        or (out.get("bio") and len(str(out["bio"]).strip()) > 2)
    )
    return out


async def build_instagram_http_client_from_playwright_page(page) -> httpx.AsyncClient | None:
    """Клиент с куками из контекста Chromium (как у страницы списка подписчиков)."""
    try:
        ua = await page.evaluate("() => navigator.userAgent")
        raw = await page.context.cookies()
        hdr = {
            "User-Agent": str(ua or "")[:512],
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "same-origin",
            "Upgrade-Insecure-Requests": "1",
            "Referer": "https://www.instagram.com/",
        }
        jar = httpx.Cookies()
        for c in raw:
            dom = (c.get("domain") or "").lower()
            if "instagram.com" not in dom:
                continue
            try:
                jar.set(
                    c["name"],
                    c["value"],
                    domain=c.get("domain"),
                    path=c.get("path") or "/",
                )
            except Exception:
                try:
                    jar.set(c["name"], c["value"])
                except Exception:
                    pass
        return httpx.AsyncClient(
            headers=hdr,
            cookies=jar,
            follow_redirects=True,
            timeout=httpx.Timeout(35.0, connect=14.0),
        )
    except Exception as exc:
        print(f"[audience] ig http client build: {exc}", file=sys.stderr)
        return None


async def fetch_instagram_member_profile_http(
    client: httpx.AsyncClient,
    username: str,
    *,
    timeout_sec: float = 28.0,
) -> dict[str, Any]:
    """GET HTML профиля подписчика; разбор через parse_instagram_profile_html."""
    un = norm_ig_username(username)
    if not un:
        return {"_ok": False, "_error": "empty_username"}
    url = f"https://www.instagram.com/{un}/"
    try:
        r = await client.get(url, timeout=timeout_sec)
        out = parse_instagram_profile_html(r.text)
        out["_http_status"] = r.status_code
        if r.status_code != 200:
            out["_ok"] = False
            if not out.get("_error"):
                out["_error"] = f"http_{r.status_code}"
        return out
    except httpx.TimeoutException:
        return {"_ok": False, "_error": "timeout", "_http_status": 0}
    except Exception as exc:
        return {"_ok": False, "_error": str(exc)[:240], "_http_status": 0}
