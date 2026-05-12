"""
Только сценарий «подписчики в модалке» для Instagram.

Код изолирован от `worker.py` (профиль/релсы) и от `audience_scrape.py` (обход подписчиков,
посты). Здесь: открытие div[role="dialog"], прокрутка, ожидание списка.

Политика продукта: не выполняем программный переход на URL вида /{user}/followers/
(полноэкранная страница). Работаем с профиля /{user}/ и модальным окном. Если после клика
Instagram открыл только URL /followers/ без модалки — вызывающий код возвращает на профиль
и повторяет попытку (см. audience_scrape).
"""
from __future__ import annotations

import asyncio
import re
import sys
import time


def norm_ig_username(u: str) -> str:
    s = (u or "").strip().lstrip("@").lower()
    s = re.sub(r"[^a-z0-9._]", "", s)
    return s


async def ig_followers_dialog_present(page) -> bool:
    try:
        return await page.locator('div[role="dialog"]').count() > 0
    except Exception:
        return False


async def ig_open_followers_modal_from_profile(page, owner: str) -> str:
    """
    Открыть модалку подписчиков кликом по ссылке в шапке / по тексту (остаёмся в сценарии профиля).
    Возвращает короткий тег для логов.
    """
    owner = norm_ig_username(owner)
    if await ig_followers_dialog_present(page):
        return "already_dialog"

    loose = [
        f'a[href*="{owner}/followers"]',
        f'a[href*="/{owner}/followers"]',
    ]
    for sel in loose:
        try:
            loc = page.locator(sel).first
            if await loc.count() == 0:
                continue
            if not await loc.is_visible():
                continue
            await loc.click(timeout=12_000)
            await asyncio.sleep(0.65)
            if await ig_followers_dialog_present(page):
                return f"ok_loose:{sel[:40]}"
        except Exception as exc:
            print(f"[audience] ig click {sel!r}: {exc}", file=sys.stderr)

    selectors = [
        f'header a[href="/{owner}/followers/"]',
        f'header a[href="/{owner}/followers"]',
        f'a[href="/{owner}/followers/"]',
        f'a[href="/{owner}/followers"]',
        f'header a[href*="{owner}/followers"]',
        'header a[href*="/followers"]',
        'section a[href*="/followers"]',
    ]
    for sel in selectors:
        try:
            loc = page.locator(sel).first
            if await loc.count() == 0:
                continue
            if not await loc.is_visible():
                continue
            await loc.click(timeout=12_000)
            await asyncio.sleep(0.65)
            if await ig_followers_dialog_present(page):
                return f"ok_sel:{sel[:48]}"
        except Exception as exc:
            print(f"[audience] ig click {sel!r}: {exc}", file=sys.stderr)

    try:
        res = await page.evaluate(
            r"""(owner) => {
                const o = owner.toLowerCase();
                const norm = (href) => {
                    try {
                        const u = new URL(href, location.origin);
                        return u.pathname.replace(/\/+$/, '').toLowerCase();
                    } catch (e) {
                        return '';
                    }
                };
                const matches = (path) =>
                    path === '/' + o + '/followers' || path.startsWith('/' + o + '/followers/');

                const tryClick = (el) => {
                    if (!el) return false;
                    el.click();
                    return true;
                };

                for (const sel of ['header a[href]', 'main a[href]', 'section a[href]', 'a[href]']) {
                    for (const a of document.querySelectorAll(sel)) {
                        const path = norm(a.getAttribute('href') || '');
                        if (!matches(path)) continue;
                        if (tryClick(a)) return 'ok_' + sel.split(' ')[0];
                    }
                }

                for (const root of [document.querySelector('header'), document.querySelector('main')]) {
                    if (!root) continue;
                    for (const el of root.querySelectorAll('[role="link"], a[href]')) {
                        const inner = el.tagName === 'A' ? el : el.querySelector('a[href]');
                        const href = (inner || el).getAttribute('href');
                        if (href && matches(norm(href))) {
                            (inner || el).click();
                            return 'ok_role_link';
                        }
                        const t = (el.textContent || '').replace(/\s+/g, ' ').trim().toLowerCase();
                        if (!t || t.length > 80) continue;
                        if (t.includes('following') || t.includes('подписок') || t.includes('posts') || t.includes('публикац')) continue;
                        if ((/\d/.test(t)) && (t.includes('follower') || t.includes('подписчик'))) {
                            el.click();
                            return 'ok_text:' + t.slice(0, 36);
                        }
                    }
                }
                return 'no_anchor';
            }""",
            owner,
        )
        await asyncio.sleep(0.65)
        if await ig_followers_dialog_present(page):
            return str(res or "ok_js")
        print(f"[audience] ig open followers js no dialog after: {res}", file=sys.stderr)
    except Exception as exc:
        print(f"[audience] ig open followers js exc: {exc}", file=sys.stderr)

    return "no_dialog"


async def ig_scroll_followers_modal(page) -> None:
    """Прокрутка списка только внутри модалки div[role="dialog"]."""
    try:
        await page.evaluate(
            r"""() => {
                const dialog = document.querySelector('div[role="dialog"]');
                if (!dialog) return;
                let best = dialog;
                let bestScore = 0;
                dialog.querySelectorAll('div').forEach((el) => {
                    const sh = el.scrollHeight;
                    const ch = el.clientHeight;
                    if (sh > ch + 40 && sh > bestScore) {
                        best = el;
                        bestScore = sh;
                    }
                });
                best.scrollTop = best.scrollHeight;
            }""",
        )
    except Exception:
        pass
    dialog = await page.query_selector('div[role="dialog"]')
    if dialog:
        try:
            await dialog.evaluate("el => { el.scrollTop = el.scrollHeight; }")
        except Exception:
            pass
    try:
        await page.mouse.wheel(0, 600)
    except Exception:
        pass


async def ig_wait_follower_user_links_in_dialog(page, owner: str, *, timeout_ms: int = 28_000) -> bool:
    """В модалке появились ссылки на профили подписчиков (не используем полноэкранный /followers/)."""
    owner = norm_ig_username(owner)
    deadline = time.monotonic() + timeout_ms / 1000.0
    while time.monotonic() < deadline:
        try:
            ok = await page.evaluate(
                r"""(owner) => {
                    const o = owner.toLowerCase();
                    const isUserHref = (href) => {
                        const h = (href || '').split('?')[0];
                        const m = h.match(/^\/([^\/]+)\/?$/);
                        if (!m) return false;
                        const u = m[1].toLowerCase();
                        return (
                            !!u &&
                            u !== o &&
                            !['p', 'reel', 'stories', 'explore', 'accounts', 'legal'].includes(u)
                        );
                    };
                    const dialog = document.querySelector('div[role="dialog"]');
                    if (!dialog) return false;
                    for (const a of dialog.querySelectorAll('a[href]')) {
                        if (isUserHref(a.getAttribute('href'))) return true;
                    }
                    return false;
                }""",
                owner,
            )
            if ok:
                return True
        except Exception:
            pass
        await asyncio.sleep(0.45)
    return False
