"""
Список подписчиков X (Twitter): страницы ``/{user}/followers`` и при необходимости
``/{user}/verified_followers``.

Селекторы: в приоритете ``[data-testid="UserCell"]`` и ссылки вида ``/handle`` внутри
ячейки — это устойчивее, чем XPath от ``/html/body/div[1]/...`` (ломается при любой
смене вёрстки). Дополнительно прокручиваем ``main``.
"""
from __future__ import annotations

import asyncio
import re
import sys

_LOGGED_IN_JS = """
    () => {
        const href = window.location.href;
        if (href.includes('/i/flow/login') || href.includes('x.com/login') ||
            href.includes('twitter.com/login')) return false;
        if (document.querySelector('[data-testid="loginButton"]')) return false;
        return !!(
            document.querySelector('[data-testid="SideNav_AccountSwitcher_Button"]') ||
            document.querySelector('[data-testid="AppTabBar_Home_Link"]') ||
            document.querySelector('[data-testid="primaryColumn"]')
        );
    }
"""

_EXTRACT_USER_CELLS_JS = """
    () => {
        const out = [];
        const seen = new Set();
        const skip = new Set(['home','explore','notifications','messages','settings','i','compose','search','intent','login','signup','following','followers','verified_followers','highlights','likes','media','lists','communities','analytics','jobs','spaces','help','tos','privacy']);

        for (const cell of document.querySelectorAll('[data-testid="UserCell"]')) {
            let handle = '';
            for (const a of cell.querySelectorAll('a[href]')) {
                const raw = (a.getAttribute('href') || '').trim();
                const m = raw.match(/^\\/([A-Za-z0-9_]{1,30})\\/?$/);
                if (!m) continue;
                const u = m[1].toLowerCase();
                if (skip.has(u)) continue;
                handle = u;
                break;
            }
            if (!handle || seen.has(handle)) continue;
            seen.add(handle);

            let displayName = '';
            const nameEl = cell.querySelector('[data-testid="UserName"]');
            if (nameEl) {
                for (const s of nameEl.querySelectorAll('span')) {
                    const t = (s.textContent || '').trim();
                    if (t && !t.startsWith('@') && s.children.length === 0) {
                        displayName = t;
                        break;
                    }
                }
            }
            if (!displayName) {
                const t2 = (cell.innerText || '').split(/\\r?\\n/).map((x) => x.trim()).filter(Boolean);
                if (t2.length) displayName = t2[0].replace(/^@\\S+\\s*/, '').slice(0, 255);
            }

            let avatar_url = '';
            const img = cell.querySelector('img[src*="pbs.twimg.com"], img[src*="profile_images"]');
            if (img) {
                avatar_url = (img.getAttribute('src') || '').trim()
                    .replace('_normal.', '_400x400.')
                    .replace('_200x200.', '_400x400.');
            }

            const bioEl = cell.querySelector('[data-testid="UserDescription"]');
            const bio = bioEl ? (bioEl.innerText || '').trim().slice(0, 2000) : '';

            const blockText = (cell.innerText || '').toLowerCase();
            const isPrivate = blockText.includes('these posts are protected') ||
                blockText.includes('защищает') ||
                blockText.includes('protected their posts');

            out.push({
                username: handle,
                display_name: displayName || handle,
                avatar_url,
                bio,
                is_private: isPrivate,
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


def _norm_x_user(u: str) -> str:
    s = (u or "").strip().lstrip("@")
    s = re.sub(r"[^A-Za-z0-9_]", "", s)
    return s


async def _scroll_followers_list(page) -> None:
    try:
        await page.evaluate(
            """() => {
                const main = document.querySelector('main');
                if (main) main.scrollTop = main.scrollHeight;
            }""",
        )
    except Exception:
        pass
    try:
        await page.mouse.wheel(0, 900)
    except Exception:
        pass


async def _collect_from_url(
    page,
    _wu,
    owner: str,
    url: str,
    seen: dict[str, dict],
    limit: int,
) -> int:
    """Добавляет строки в ``seen``; возвращает число новых за этот заход."""
    before = len(seen)
    await page.goto(url, wait_until="domcontentloaded", timeout=60_000)
    if _wu is not None and hasattr(_wu, "wait_for_anti_bot_clear"):
        await _wu.wait_for_anti_bot_clear(page, platform="x")
    await page.wait_for_timeout(1600)

    if not await page.evaluate(_LOGGED_IN_JS):
        raise RuntimeError(
            "X требует авторизации — нажмите «Войти в X» в настройках приложения.",
        )

    stagnant = 0
    prev = 0
    for i in range(90):
        if len(seen) >= limit:
            break
        rows = await page.evaluate(_EXTRACT_USER_CELLS_JS)
        if isinstance(rows, list):
            for raw in rows:
                if not isinstance(raw, dict):
                    continue
                un = str(raw.get("username") or "").strip().lower()
                if not un or un == owner.lower():
                    continue
                if un not in seen:
                    seen[un] = raw
        now = len(seen)
        if now <= prev:
            stagnant += 1
        else:
            stagnant = 0
        prev = now
        if stagnant >= 12:
            break
        await _scroll_followers_list(page)
        await asyncio.sleep(0.35 + (i % 5) * 0.05)
    return len(seen) - before


async def scrape_x_audience_followers(
    page,
    _wu,
    owner_username: str,
    limit: int,
    *,
    max_posts_per_follower: int = 0,
    skip_existing_member_profiles: bool = False,
    audience_account_id: int | None = None,
) -> dict:
    del max_posts_per_follower  # для X не используется (совместимость сигнатуры с TikTok/IG)

    owner = _norm_x_user(owner_username)
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
            print(f"[audience] x skip_existing: не удалось прочитать БД: {exc}", file=sys.stderr)

    followers_url = f"https://x.com/{owner}/followers"
    verified_url = f"https://x.com/{owner}/verified_followers"

    print(f"[audience] x: открываем {followers_url}", file=sys.stderr)
    try:
        added = await _collect_from_url(page, _wu, owner, followers_url, seen, limit)
    except RuntimeError as exc:
        return {"error": str(exc)}
    print(f"[audience] x: после /followers записей={len(seen)} (+{added})", file=sys.stderr)

    if len(seen) < limit:
        print(f"[audience] x: добираем из {verified_url}", file=sys.stderr)
        try:
            added_v = await _collect_from_url(page, _wu, owner, verified_url, seen, limit)
        except RuntimeError as exc:
            if not seen:
                return {"error": str(exc)}
            added_v = 0
            print(f"[audience] x: verified_followers пропущен: {exc}", file=sys.stderr)
        print(f"[audience] x: после /verified_followers записей={len(seen)} (+{added_v})", file=sys.stderr)

    followers: list[dict] = []
    for un, row in seen.items():
        if len(followers) >= limit:
            break
        if skip_existing_member_profiles and skip_usernames and un in skip_usernames:
            followers.append({"username": un, "_reuse_existing": True})
            continue
        followers.append(dict(row))

    if not followers:
        return {
            "error": (
                "Не удалось прочитать список подписчиков X. "
                "Проверьте вход, откройте вручную страницы «Followers» / «Verified followers» "
                "и при необходимости пришлите скрин DOM: предпочтительны селекторы "
                "``[data-testid=\"UserCell\"]`` или короткий CSS от ``main``, а не XPath от корня документа."
            ),
        }

    return {"followers": followers, "owner_username": owner}
