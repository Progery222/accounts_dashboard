"""
Список подписчиков Threads: со страницы профиля клик по счётчику
«{число} подписчиков / followers / subscribers» — открывается модалка; при сбое — прямой URL ``/@user/followers``.
"""
from __future__ import annotations

import asyncio
import re
import sys

_LOGGED_IN_HINT_JS = """
    () => {
        const href = window.location.href;
        if (href.includes('/login')) return false;
        if (document.querySelector('input[type="password"]') &&
            (document.querySelector('input[autocomplete="email"]') ||
             document.querySelector('input[autocomplete="username"]'))) return false;
        return !!(
            document.querySelector('[aria-label*="New thread"]') ||
            document.querySelector('[aria-label*="Новый тред"]') ||
            document.querySelector('[aria-label*="Create"]') ||
            document.querySelector('a[href="/"][aria-label*="Home"]')
        );
    }
"""

_CLICK_FOLLOWERS_STATS_JS = """
    (owner) => {
        const o = String(owner || '').replace(/^@/, '').toLowerCase();
        const normPath = (href) => {
            try {
                return new URL(href, location.origin).pathname.replace(/\\/+$/, '').toLowerCase();
            } catch (e) {
                return '';
            }
        };
        const followersPathOk = (p) =>
            p === ('/@' + o + '/followers') || p.endsWith('/' + o + '/followers') || p.includes('/@' + o + '/followers');

        for (const a of document.querySelectorAll('a[href]')) {
            const h = a.getAttribute('href') || '';
            const p = normPath(h);
            if (!p.includes('followers')) continue;
            if (!followersPathOk(p)) continue;
            const t = (a.textContent || '').replace(/\\s+/g, ' ').trim();
            if (t.length > 120) continue;
            const hasDigit = /\\d/.test(t);
            const hasKw = /(followers?|подписчик|subscribers?)/i.test(t);
            if (hasDigit && hasKw) {
                a.click();
                return 'href:' + p.slice(0, 48);
            }
            if (hasDigit || hasKw) {
                a.click();
                return 'href_loose:' + p.slice(0, 48);
            }
            a.click();
            return 'href_exact:' + p.slice(0, 48);
        }

        const kw = /(followers?|подписчик|subscribers?)/i;
        for (const el of document.querySelectorAll('a[href], [role="link"]')) {
            const t = (el.textContent || '').replace(/\\s+/g, ' ').trim();
            if (t.length < 4 || t.length > 96) continue;
            if (!/\\d/.test(t) || !kw.test(t)) continue;
            const href = (el.getAttribute('href') || '').toLowerCase();
            if (href && (href.includes('login') || href.includes('help'))) continue;
            const clickEl = el.tagName === 'A' ? el : el.querySelector('a[href]');
            (clickEl || el).click();
            return 'text:' + t.slice(0, 48);
        }
        return 'none';
    }
"""

_EXTRACT_FOLLOWERS_MODAL_JS = """
    (owner) => {
        const o = String(owner || '').replace(/^@/, '').toLowerCase();
        const dialog = document.querySelector('div[role="dialog"]');
        const root = dialog || document.querySelector('main') || document.body;
        const out = [];
        const seen = new Set();
        const skip = new Set([o, 'followers', 'following', 'activity', 'search', 'explore']);

        for (const a of root.querySelectorAll('a[href^="/@"]')) {
            const raw = (a.getAttribute('href') || '').split('?')[0].trim();
            const m = raw.match(/^\\/(@[A-Za-z0-9._]+)\\/?$/);
            if (!m) continue;
            const handle = m[1].replace(/^@/, '').toLowerCase();
            if (!handle || handle === o || seen.has(handle) || skip.has(handle)) continue;
            seen.add(handle);

            let displayName = handle;
            const row = a.closest('[role="listitem"]') || a.closest('div');
            if (row) {
                const inner = (row.innerText || '').split(/\\r?\\n/).map((x) => x.trim()).filter(Boolean);
                if (inner.length && inner[0] && !inner[0].startsWith('@')) displayName = inner[0].slice(0, 255);
            }

            let avatar_url = '';
            const scope = row || a.parentElement;
            if (scope) {
                const img = scope.querySelector('img[src*="cdninstagram"], img[src*="fbcdn"], img[src*="instagram"]');
                if (img) avatar_url = (img.getAttribute('src') || '').trim().slice(0, 2048);
            }

            out.push({
                username: handle,
                display_name: displayName,
                avatar_url,
                bio: '',
                is_private: false,
                external_id: handle,
                follower_count: 0,
                following_count: 0,
                like_count: 0,
            });
            if (out.length >= 500) break;
        }
        return out;
    }
"""


def _norm_threads_user(u: str) -> str:
    s = (u or "").strip().lstrip("@").lower()
    s = re.sub(r"[^a-z0-9._]", "", s)
    return s


async def _dialog_visible(page) -> bool:
    try:
        loc = page.locator('div[role="dialog"]')
        return await loc.count() > 0 and await loc.first.is_visible()
    except Exception:
        return False


async def _scroll_followers_container(page) -> None:
    try:
        await page.evaluate(
            """() => {
                const d = document.querySelector('div[role="dialog"]');
                const root = d || document.querySelector('main');
                if (!root) return;
                let best = root;
                let score = 0;
                root.querySelectorAll('div').forEach((el) => {
                    const sh = el.scrollHeight;
                    const ch = el.clientHeight;
                    if (sh > ch + 30 && sh > score) {
                        best = el;
                        score = sh;
                    }
                });
                best.scrollTop = best.scrollHeight;
            }""",
        )
    except Exception:
        pass
    try:
        await page.mouse.wheel(0, 700)
    except Exception:
        pass


async def scrape_threads_audience_followers(
    page,
    _wu,
    owner_username: str,
    limit: int,
    *,
    max_posts_per_follower: int = 0,
    skip_existing_member_profiles: bool = False,
    audience_account_id: int | None = None,
) -> dict:
    del max_posts_per_follower

    owner = _norm_threads_user(owner_username)
    if not owner:
        return {"error": "Пустой username"}

    limit = max(1, min(int(limit or 100), 500))
    seen: dict[str, dict] = {}

    skip_usernames: set[str] = set()
    if skip_existing_member_profiles and audience_account_id:
        try:
            from platforms.audience_skip import existing_audience_usernames_for_dashboard_account

            skip_usernames = await asyncio.to_thread(
                existing_audience_usernames_for_dashboard_account,
                int(audience_account_id),
            )
        except Exception as exc:
            print(f"[audience] threads skip_existing: не удалось прочитать БД: {exc}", file=sys.stderr)

    profile_url = f"https://www.threads.com/@{owner}"
    await page.goto(profile_url, wait_until="domcontentloaded", timeout=60_000)
    if _wu is not None and hasattr(_wu, "wait_for_anti_bot_clear"):
        await _wu.wait_for_anti_bot_clear(page, platform="threads")
    await page.wait_for_timeout(2200)

    opened = await page.evaluate(_CLICK_FOLLOWERS_STATS_JS, owner)
    print(f"[audience] threads: клик по блоку подписчиков → {opened}", file=sys.stderr)
    await page.wait_for_timeout(900)

    if not await _dialog_visible(page):
        print("[audience] threads: модалка не открылась — пробуем прямой /followers/", file=sys.stderr)
        await page.goto(f"https://www.threads.com/@{owner}/followers", wait_until="domcontentloaded", timeout=60_000)
        if _wu is not None and hasattr(_wu, "wait_for_anti_bot_clear"):
            await _wu.wait_for_anti_bot_clear(page, platform="threads")
        await page.wait_for_timeout(1400)

    stagnant = 0
    prev = 0
    for i in range(85):
        if len(seen) >= limit:
            break
        rows = await page.evaluate(_EXTRACT_FOLLOWERS_MODAL_JS, owner)
        if isinstance(rows, list):
            for raw in rows:
                if not isinstance(raw, dict):
                    continue
                un = str(raw.get("username") or "").strip().lower()
                if not un or un == owner:
                    continue
                if un not in seen:
                    seen[un] = raw
        now = len(seen)
        if now <= prev:
            stagnant += 1
        else:
            stagnant = 0
        prev = now
        if stagnant >= 14:
            break
        await _scroll_followers_container(page)
        await asyncio.sleep(0.32 + (i % 6) * 0.04)

    followers: list[dict] = []
    for un, row in seen.items():
        if len(followers) >= limit:
            break
        if skip_existing_member_profiles and skip_usernames and un in skip_usernames:
            followers.append({"username": un, "_reuse_existing": True})
            continue
        followers.append(dict(row))

    if not followers:
        hint = ""
        try:
            logged = await page.evaluate(_LOGGED_IN_HINT_JS)
            if not logged:
                hint = " Войдите в Threads в настройках браузера worker."
        except Exception:
            pass
        return {
            "error": (
                "Не удалось прочитать список подписчиков Threads."
                + hint
                + " Убедитесь, что на профиле видна ссылка «подписчиков» / followers и повторите съём."
            ),
        }

    return {"followers": followers, "owner_username": owner}
