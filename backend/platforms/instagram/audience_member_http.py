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


def _parse_ig_count_token(raw: str) -> int:
    """'378' / '1.2K' / '1 107' → int."""
    s = str(raw or "").strip().replace("\u00a0", "").replace("\u202f", "").replace(" ", "").replace(",", "")
    if not s:
        return 0
    m = re.match(r"^([\d]+(?:[.,][\d]+)?)\s*([KMBkmb]?)$", s.replace(",", "."))
    if m:
        try:
            num = float(m.group(1))
            mult = {"K": 1_000, "M": 1_000_000, "B": 1_000_000_000}.get(m.group(2).upper(), 1)
            return int(num * mult)
        except ValueError:
            pass
    digits = re.sub(r"[^\d]", "", s)
    return int(digits) if digits else 0


def _parse_ig_counts_from_meta_description(text: str) -> tuple[int, int, int]:
    """Из meta description: «4 posts, 378 followers, 1107 following - …»."""
    if not text:
        return 0, 0, 0
    t = _html_unescape(text).strip()
    posts = followers = following = 0
    p_m = re.search(r"([\d.,\s]+[KMBkmb]?)\s+posts?\b", t, re.I)
    f_m = re.search(r"([\d.,\s]+[KMBkmb]?)\s+followers?\b", t, re.I)
    fo_m = re.search(r"([\d.,\s]+[KMBkmb]?)\s+following\b", t, re.I)
    if p_m:
        posts = _parse_ig_count_token(p_m.group(1))
    if f_m:
        followers = _parse_ig_count_token(f_m.group(1))
    if fo_m:
        following = _parse_ig_count_token(fo_m.group(1))
    return posts, followers, following


IG_PROFILE_COUNTS_FROM_DOM_JS = r"""
(() => {
    const toInt = (raw) => {
        const s = String(raw || '').replace(/\u00a0|\u202f|\s/g, '').replace(/,/g, '');
        const m = s.match(/([\d]+(?:\.[\d]+)?)\s*([KMBkmb]?)/i);
        if (!m) {
            const d = s.replace(/[^\d]/g, '');
            return d ? parseInt(d, 10) : 0;
        }
        const n = parseFloat(m[1]);
        const suf = (m[2] || '').toLowerCase();
        const mul = suf === 'k' ? 1e3 : suf === 'm' ? 1e6 : suf === 'b' ? 1e9 : 1;
        return Math.round(n * mul);
    };
    const extractFromStatLink = (a) => {
        if (!a) return 0;
        const aria = (a.getAttribute('aria-label') || '').trim();
        let m = aria.match(/([\d.,]+\s*[KMBkmb]?)/);
        if (m) return toInt(m[1]);
        const title = (a.getAttribute('title') || '').trim();
        m = title.match(/([\d.,]+\s*[KMBkmb]?)/);
        if (m) return toInt(m[1]);
        for (const sp of a.querySelectorAll('span[title], span')) {
            const t = (sp.getAttribute('title') || sp.textContent || '').trim();
            if (!t) continue;
            if (/^[\d.,]+\s*[KMBkmb]?$/i.test(t.replace(/\s/g, ''))) return toInt(t);
            m = t.match(/^([\d.,]+\s*[KMBkmb]?)/);
            if (m) return toInt(m[1]);
        }
        const lines = (a.innerText || '').split(/\n/).map((x) => x.trim()).filter(Boolean);
        for (const line of lines) {
            const compact = line.replace(/\s/g, '');
            if (/^[\d.,]+[KMBkmb]?$/i.test(compact)) return toInt(line);
        }
        const blob = (a.innerText || '').replace(/\s+/g, ' ');
        m = blob.match(/([\d.,]+\s*[KMBkmb]?)/);
        return m ? toInt(m[1]) : 0;
    };
    const out = { followers: 0, following: 0, posts: 0 };
    try {
        const root = document.querySelector('header') || document;
        const pick = (kind) => {
            for (const a of root.querySelectorAll(`a[href*="/${kind}"]`)) {
                const href = (a.getAttribute('href') || '').toLowerCase();
                if (!href.includes(`/${kind}`)) continue;
                if (href.includes('/accounts/')) continue;
                const n = extractFromStatLink(a);
                if (n > 0) return n;
            }
            return 0;
        };
        out.followers = pick('followers');
        out.following = pick('following');
        const postsLink = root.querySelector('a[href*="/posts"]') || root.querySelector('a[href*="/reels"]');
        if (postsLink) out.posts = extractFromStatLink(postsLink);
        const items = Array.from(root.querySelectorAll('header section ul li, section ul li'));
        for (const li of items) {
            const txt = (li.textContent || '').replace(/\s+/g, ' ').trim();
            if (!txt) continue;
            const m = txt.match(/([\d.,]+\s*[KMBkmb]?)/);
            const val = m ? toInt(m[1]) : 0;
            const low = txt.toLowerCase();
            if (!out.posts && /(posts?|публикац)/i.test(low)) out.posts = val;
            else if (!out.followers && /(followers?|подписчик)/i.test(low)) out.followers = val;
            else if (!out.following && /(following|подписк)/i.test(low)) out.following = val;
        }
        if (!out.followers || !out.following) {
            const text = (root.innerText || '').replace(/\s+/g, ' ');
            const mf = text.match(/([\d.,]+\s*[KMBkmb]?)\s+followers?/i);
            const mfo = text.match(/([\d.,]+\s*[KMBkmb]?)\s+following/i);
            const mp = text.match(/([\d.,]+\s*[KMBkmb]?)\s+posts?/i);
            if (!out.followers && mf) out.followers = toInt(mf[1]);
            if (!out.following && mfo) out.following = toInt(mfo[1]);
            if (!out.posts && mp) out.posts = toInt(mp[1]);
        }
    } catch (_) {}
    return out;
})()
"""


async def ig_wait_profile_stats(page, *, timeout_ms: int = 35_000) -> None:
    """Дождаться появления цифр в блоке followers/following."""
    try:
        await page.wait_for_function(
            r"""() => {
                const h = document.querySelector('header') || document;
                const fl = h.querySelector('a[href*="/followers"]');
                if (!fl) return false;
                const t = (fl.innerText || fl.getAttribute('aria-label') || '');
                return /\d/.test(t);
            }""",
            timeout=timeout_ms,
        )
    except Exception:
        await page.wait_for_timeout(2800)


async def ig_merge_profile_snap_from_http(page, username: str, snap: dict[str, Any]) -> dict[str, Any]:
    """Доп. GET с куками страницы — meta description часто содержит счётчики."""
    client = await build_instagram_http_client_from_playwright_page(page)
    if client is None:
        return snap
    try:
        http_snap = await fetch_instagram_member_profile_http(client, username, timeout_sec=28.0)
        for ck in ("follower_count", "following_count"):
            if int(snap.get(ck) or 0) <= 0 and int(http_snap.get(ck) or 0) > 0:
                snap[ck] = int(http_snap[ck])
        if not (snap.get("display_name") or "").strip() and (http_snap.get("display_name") or "").strip():
            snap["display_name"] = http_snap["display_name"]
        if not (snap.get("bio") or "").strip() and (http_snap.get("bio") or "").strip():
            snap["bio"] = http_snap["bio"]
        if not (snap.get("avatar_url") or "").strip() and (http_snap.get("avatar_url") or "").strip():
            snap["avatar_url"] = http_snap["avatar_url"]
    finally:
        await client.aclose()
    return snap


async def ig_extract_profile_counts_from_page(page) -> dict[str, int]:
    """Счётчики из отрендеренного DOM (надёжнее, чем сырой HTML без JSON)."""
    try:
        stats = await page.evaluate(IG_PROFILE_COUNTS_FROM_DOM_JS)
    except Exception as exc:
        print(f"[audience] ig dom counts: {exc}", file=sys.stderr)
        return {"followers": 0, "following": 0, "posts": 0}
    if not isinstance(stats, dict):
        return {"followers": 0, "following": 0, "posts": 0}
    return {
        "followers": max(0, int(stats.get("followers") or 0)),
        "following": max(0, int(stats.get("following") or 0)),
        "posts": max(0, int(stats.get("posts") or 0)),
    }


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
    if not html or len(html) < 80:
        return out

    low = html.lower()
    if "accounts/login" in low and "password" in low and "username" in low:
        out["_auth_required"] = True
        return out

    if re.search(r'"is_private"\s*:\s*true\b', html):
        out["is_private"] = True

    for pat in (
        r'"edge_followed_by"\s*:\s*\{\s*"count"\s*:\s*(\d+)',
        r'"follower_count"\s*:\s*(\d+)',
        r'"followers_count"\s*:\s*(\d+)',
    ):
        m = re.search(pat, html)
        if m:
            out["follower_count"] = max(0, int(m.group(1)))
            break
    for pat in (
        r'"edge_follow"\s*:\s*\{\s*"count"\s*:\s*(\d+)',
        r'"following_count"\s*:\s*(\d+)',
        r'"followees_count"\s*:\s*(\d+)',
    ):
        m = re.search(pat, html)
        if m:
            out["following_count"] = max(0, int(m.group(1)))
            break

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

    meta_desc = (
        re.search(r'<meta\s+name="description"\s+content="([^"]*)"', html, re.I)
        or re.search(r'<meta\s+property="og:description"\s+content="([^"]*)"', html, re.I)
    )
    if meta_desc:
        c_raw = _html_unescape(meta_desc.group(1)).strip()
        _posts, _followers, _following = _parse_ig_counts_from_meta_description(c_raw)
        if _followers > 0:
            out["follower_count"] = _followers
        if _following > 0:
            out["following_count"] = _following
        c = c_raw
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
