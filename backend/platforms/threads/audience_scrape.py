"""
Список подписчиков Threads: со страницы профиля клик по надписи
«{число} follower(s) / подписчиков …» (часто не ``<a>``) или по ссылке на ``/followers`` —
открывается модалка. Переход на отдельный URL ``/@user/followers`` не используется.
"""
from __future__ import annotations

import asyncio
import random
import re
import sys

_THREADS_MEMBER_PROFILE_GAP_SEC = (1.5, 3.0)


def _parse_threads_count(text: str) -> int:
    if not text:
        return 0
    text = str(text).strip().replace("\xa0", "").replace("\u202f", "").replace(" ", "")
    m = re.match(r"^([\d]+(?:[.,][\d]+)?)\s*([KMBkmb]?)$", text.replace(",", "."))
    if m:
        try:
            num = float(m.group(1))
            mult = {"K": 1_000, "M": 1_000_000, "B": 1_000_000_000}.get(m.group(2).upper(), 1)
            return int(num * mult)
        except ValueError:
            pass
    digits = re.sub(r"[^\d]", "", text)
    return int(digits) if digits else 0


async def _threads_enrich_follower_profile_playwright(page, _wu, row: dict) -> None:
    username = _norm_threads_user(str(row.get("username") or ""))
    if not username:
        return
    from platforms.threads.worker import threads_nav_timeout_ms

    print(f"[audience] threads enrich: открываем @{username}", file=sys.stderr)
    await page.goto(
        f"https://www.threads.com/@{username}",
        wait_until="domcontentloaded",
        timeout=threads_nav_timeout_ms(),
    )
    if _wu is not None and hasattr(_wu, "wait_for_anti_bot_clear"):
        await _wu.wait_for_anti_bot_clear(page, platform="threads")
    await page.wait_for_timeout(2200)
    info = await page.evaluate(
        """(username) => {
            let displayName = '';
            const h1 = document.querySelector('h1');
            if (h1) displayName = h1.textContent.trim();
            let followers = '';
            const followerLink =
                document.querySelector(`a[href="/@${username}/followers"]`) ||
                document.querySelector('a[href*="/followers"]');
            if (followerLink) {
                const t = followerLink.textContent.trim();
                const m = t.match(/^(\\d[\\d,. ]*[KkMmBb]?)/);
                if (m) followers = m[1].replace(/\\s/g, '');
            }
            let bio = '';
            const metaDesc = document.querySelector('meta[name="description"]');
            if (metaDesc) bio = (metaDesc.getAttribute('content') || '').split(' - See ')[0].trim();
            let avatar = '';
            const og = document.querySelector('meta[property="og:image"]');
            if (og) avatar = og.getAttribute('content') || '';
            return { displayName, followers, bio, avatar };
        }""",
        username,
    )
    if isinstance(info, dict):
        row["display_name"] = str(info.get("displayName") or row.get("display_name") or "")[:255]
        row["bio"] = str(info.get("bio") or row.get("bio") or "")[:4000]
        row["avatar_url"] = str(info.get("avatar") or row.get("avatar_url") or "")[:2048]
        row["follower_count"] = _parse_threads_count(str(info.get("followers") or "")) or int(
            row.get("follower_count") or 0
        )
        row["_enrich_ok"] = bool(
            str(row.get("display_name") or "").strip()
            or int(row.get("follower_count") or 0) > 0
            or len(str(row.get("bio") or "").strip()) > 2
        )
        row["_enrich_note"] = "" if row["_enrich_ok"] else "Мало данных на странице"

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

        /** Сначала надпись «1 follower» / «N followers» (threads.net) — без перехода на /followers. */
        const badFollowingLine = (txt) =>
            /\\b\\d[\\d,\\s]*\\s*following\\b/i.test(txt) ||
            /^\\s*\\d[\\d,\\s]*\\s*подписок\\b/i.test(txt) ||
            /\\bв\\s+подписках\\b/i.test(txt);
        const goodFollowersStat = (txt) => {
            const t = (txt || '').replace(/\\s+/g, ' ').trim();
            if (t.length < 6 || t.length > 96) return false;
            if (badFollowingLine(t)) return false;
            return /^\\d[\\d,\\s]*\\s+(follower|followers|subscribers?|подписчик)/i.test(t);
        };
        const scored = [];
        for (const el of document.querySelectorAll(
            'span, a, button, [role="button"], [role="link"], div'
        )) {
            const t = (el.textContent || '').replace(/\\s+/g, ' ').trim();
            if (!goodFollowersStat(t)) continue;
            const cs = window.getComputedStyle(el);
            if (cs.display === 'none' || cs.visibility === 'hidden' || parseFloat(cs.opacity || '1') === 0) {
                continue;
            }
            const r = el.getBoundingClientRect();
            if (r.width < 10 || r.height < 8 || r.bottom < 0 || r.top > innerHeight + 80) continue;
            const role = el.getAttribute('role') || '';
            let prio = r.width * r.height;
            if (el.tagName === 'A' || role === 'link' || role === 'button' || el.tagName === 'BUTTON') {
                prio -= 50000;
            }
            scored.push({ el, t, prio });
        }
        scored.sort((x, y) => x.prio - y.prio || x.t.length - y.t.length);
        if (scored.length) {
            const { el, t } = scored[0];
            el.click();
            return 'stat_text:' + t.slice(0, 64);
        }

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
    list_only: bool = False,
    enrich_only: bool = False,
    enrich_usernames: list[str] | None = None,
) -> dict:
    del max_posts_per_follower

    owner = _norm_threads_user(owner_username)
    if not owner:
        return {"error": "Пустой username"}
    if enrich_only and not audience_account_id:
        return {"error": "Режим enrich требует audience_account_id."}

    limit = max(1, min(int(limit or 100), 500))

    if enrich_only:
        from platforms.audience_skip import (
            existing_audience_member_rows_for_dashboard_account,
            filter_audience_followers_by_usernames,
        )

        followers = await asyncio.to_thread(
            existing_audience_member_rows_for_dashboard_account,
            int(audience_account_id),
            limit=limit,
        )
        followers = filter_audience_followers_by_usernames(followers, enrich_usernames)
        if not followers:
            return {"error": "Нет подписчиков в БД для обогащения."}
        for i, row in enumerate(followers):
            if i > 0:
                lo, hi = _THREADS_MEMBER_PROFILE_GAP_SEC
                await asyncio.sleep(lo + random.random() * (hi - lo))
            row["posts"] = []
            try:
                await _threads_enrich_follower_profile_playwright(page, _wu, row)
            except Exception as exc:
                print(
                    f"[audience] threads enrich (внешний) @{row.get('username')}: {exc}",
                    file=sys.stderr,
                )
        return {"followers": followers, "owner_username": owner, "audience_mode": "enrich"}

    seen: dict[str, dict] = {}

    skip_usernames: set[str] = set()
    if (skip_existing_member_profiles or enrich_only) and audience_account_id:
        try:
            from platforms.audience_skip import existing_audience_usernames_for_dashboard_account

            skip_usernames = await asyncio.to_thread(
                existing_audience_usernames_for_dashboard_account,
                int(audience_account_id),
            )
        except Exception as exc:
            print(f"[audience] threads skip_existing: не удалось прочитать БД: {exc}", file=sys.stderr)

    if enrich_only and enrich_usernames:
        want = {str(u or "").strip().lstrip("@").lower() for u in enrich_usernames if str(u or "").strip()}
        if want:
            skip_usernames = {u for u in skip_usernames if u in want}

    from platforms.threads.worker import threads_nav_timeout_ms

    profile_url = f"https://www.threads.com/@{owner}"
    await page.goto(
        profile_url,
        wait_until="domcontentloaded",
        timeout=threads_nav_timeout_ms(),
    )
    if _wu is not None and hasattr(_wu, "wait_for_anti_bot_clear"):
        await _wu.wait_for_anti_bot_clear(page, platform="threads")
    await page.wait_for_timeout(2200)

    for attempt in range(2):
        opened = await page.evaluate(_CLICK_FOLLOWERS_STATS_JS, owner)
        print(f"[audience] threads: клик по блоку подписчиков → {opened}", file=sys.stderr)
        await page.wait_for_timeout(1100 if attempt else 900)
        if await _dialog_visible(page):
            break
        try:
            await page.evaluate("() => window.scrollTo(0, 0)")
        except Exception:
            pass
        await page.wait_for_timeout(400)

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
        if enrich_only and skip_usernames and un not in skip_usernames:
            continue
        if skip_existing_member_profiles and skip_usernames and un in skip_usernames:
            d = dict(row)
            d["_reuse_existing"] = True
            followers.append(d)
            continue
        followers.append(dict(row))

    if enrich_only and not followers and skip_usernames:
        return {"error": "Не удалось обновить подписчиков Threads — список пуст или нет совпадений с БД."}

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
                + " На странице профиля нажмите на строку с числом подписчиков"
                + " (например «1 follower» / «N followers»), чтобы открылась модалка, и повторите съём."
            ),
        }

    if list_only:
        out_mode = "list"
    elif enrich_only:
        out_mode = "enrich"
    else:
        out_mode = "full"
    return {"followers": followers, "owner_username": owner, "audience_mode": out_mode}
