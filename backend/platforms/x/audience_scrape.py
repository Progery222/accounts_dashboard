"""
Список подписчиков X (Twitter): страницы ``/{user}/followers`` и при необходимости
``/{user}/verified_followers``.

Селекторы: ``[data-testid="UserCell"]`` только внутри основной колонки (и при
возможности — региона ленты подписчиков по ``aria-label``), чтобы не подтягивать
«Who to follow» из ``sidebarColumn``.
"""
from __future__ import annotations

import asyncio
import random
import re
import sys

_X_MEMBER_PROFILE_GAP_SEC = (1.5, 3.0)


def _parse_x_count(text: str) -> int:
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


async def _x_enrich_follower_profile_playwright(page, _wu, row: dict) -> None:
    username = _norm_x_user(str(row.get("username") or ""))
    if not username:
        return
    print(f"[audience] x enrich: открываем @{username}", file=sys.stderr)
    await page.goto(
        f"https://x.com/{username}",
        wait_until="domcontentloaded",
        timeout=60_000,
    )
    if _wu is not None and hasattr(_wu, "wait_for_anti_bot_clear"):
        await _wu.wait_for_anti_bot_clear(page, platform="x")
    await page.wait_for_timeout(1800)
    if not await page.evaluate(_LOGGED_IN_JS):
        print(f"[audience] x enrich @{username}: требуется вход", file=sys.stderr)
        row["_enrich_ok"] = False
        row["_enrich_note"] = "Требуется вход в X"
        return
    try:
        await page.wait_for_selector('[data-testid="UserName"]', timeout=25_000)
    except Exception:
        print(f"[audience] x enrich @{username}: профиль не загрузился", file=sys.stderr)
        row["_enrich_ok"] = False
        row["_enrich_note"] = "Профиль не загрузился"
        return
    info = await page.evaluate(
        """(username) => {
            let displayName = '';
            const nameEl = document.querySelector('[data-testid="UserName"]');
            if (nameEl) {
                for (const s of nameEl.querySelectorAll('span')) {
                    const t = (s.textContent || '').trim();
                    if (t && !t.startsWith('@') && s.children.length === 0) {
                        displayName = t; break;
                    }
                }
            }
            const bioEl = document.querySelector('[data-testid="UserDescription"]');
            const bio = bioEl ? bioEl.innerText.trim() : '';
            let followers = '';
            const col = document.querySelector('[data-testid="primaryColumn"]') || document;
            for (const a of col.querySelectorAll('a[href]')) {
                const href = (a.getAttribute('href') || '').toLowerCase();
                if (href.includes(`/${username.toLowerCase()}/followers`)) {
                    const t = (a.getAttribute('aria-label') || a.innerText || '').trim();
                    const m = t.match(/([\\d,.]+[KkMmBb]?)/);
                    if (m) { followers = m[1]; break; }
                }
            }
            let avatar = '';
            const img = document.querySelector('[data-testid^="UserAvatar-Container"] img');
            if (img) avatar = img.src || '';
            return { displayName, bio, followers, avatar };
        }""",
        username,
    )
    if isinstance(info, dict):
        row["display_name"] = str(info.get("displayName") or row.get("display_name") or "")[:255]
        row["bio"] = str(info.get("bio") or row.get("bio") or "")[:4000]
        row["avatar_url"] = str(info.get("avatar") or row.get("avatar_url") or "")[:2048]
        row["follower_count"] = _parse_x_count(str(info.get("followers") or "")) or int(
            row.get("follower_count") or 0
        )
        row["_enrich_ok"] = bool(
            str(row.get("display_name") or "").strip()
            or int(row.get("follower_count") or 0) > 0
            or len(str(row.get("bio") or "").strip()) > 2
        )
        row["_enrich_note"] = "" if row["_enrich_ok"] else "Мало данных на странице"

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

        /** Био в /followers часто без UserDescription — очищаем клон ячейки от имени и кнопок. */
        function bioFromUserCell(cellEl, handleLower) {
            const desc = cellEl.querySelector('[data-testid="UserDescription"]');
            if (desc) {
                const t0 = (desc.innerText || '').trim();
                if (t0) return t0.slice(0, 2000);
            }
            try {
                const sub = cellEl.cloneNode(true);
                const nb = sub.querySelector('[data-testid="UserName"]');
                if (nb) nb.remove();
                for (const el of sub.querySelectorAll('button')) el.remove();
                for (const el of sub.querySelectorAll('[role="button"]')) el.remove();
                let t = (sub.innerText || '').replace(/[\\u00a0\\u202f]/g, ' ').replace(/\\s+/g, ' ').trim();
                if (t) {
                    const privRe = /these posts are protected|защищает|protected their posts|^followed by\\b/i;
                    if (!privRe.test(t)) {
                        t = t.replace(new RegExp('@' + handleLower + '\\\\b', 'gi'), ' ').trim();
                        t = t.replace(/\\b(Follow|Following|Подписаться|Отписаться|Читать|Читаю)\\b/gi, ' ').trim();
                        t = t.replace(/\\s+/g, ' ').trim();
                        if (t.length > 4) return t.slice(0, 2000);
                    }
                }
            } catch (_) {}
            const nameBlock = cellEl.querySelector('[data-testid="UserName"]');
            const sk = new Set();
            if (nameBlock) {
                sk.add((nameBlock.innerText || '').replace(/\\s+/g, ' ').trim());
                for (const s of nameBlock.querySelectorAll('span')) {
                    const x = (s.textContent || '').trim();
                    if (x) sk.add(x);
                }
            }
            sk.add('@' + handleLower);
            const privRe2 = /these posts are protected|защищает|protected their posts|followed by\\b/i;
            let best = '';
            for (const el of cellEl.querySelectorAll('[dir="auto"]')) {
                if (nameBlock && nameBlock.contains(el)) continue;
                const tx = (el.textContent || '').replace(/\\s+/g, ' ').trim();
                if (!tx || tx.length < 2 || privRe2.test(tx)) continue;
                if (sk.has(tx)) continue;
                if (/^(follow|following|подпис|читать|читаю)$/i.test(tx)) continue;
                if (tx.length > best.length) best = tx;
            }
            if (best.length > 4) return best.slice(0, 2000);
            const lines = (cellEl.innerText || '')
                .split(/\\r?\\n/)
                .map((x) => x.replace(/\\s+/g, ' ').trim())
                .filter(Boolean);
            for (const line of lines) {
                if (!line || line.length < 4) continue;
                if (sk.has(line)) continue;
                if (privRe2.test(line)) continue;
                if (/^(follow|following)$/i.test(line)) continue;
                if (/^@\\w{1,30}$/.test(line)) continue;
                if (/^[\\d.,\\sKkMmBb]+$/.test(line)) continue;
                if (line.length > best.length) best = line;
            }
            return best.slice(0, 2000);
        }

        const sidebar =
            document.querySelector('[data-testid="sidebarColumn"]') ||
            document.querySelector('[data-testid="secondaryColumn"]');
        const primary = document.querySelector('[data-testid="primaryColumn"]');

        /** Регион списка подписчиков (не сайдбар «Who to follow»). */
        function findFollowersListRoot(primaryEl) {
            if (!primaryEl) return null;
            let best = null;
            let bestCount = 0;
            for (const el of primaryEl.querySelectorAll('[aria-label]')) {
                const a = (el.getAttribute('aria-label') || '').toLowerCase();
                if (!a) continue;
                if (a.includes('who to follow') || a.includes('кого читать') || a.includes('кому следовать')) {
                    continue;
                }
                const looksFollowers =
                    (a.includes('follower') &&
                        (a.includes('timeline') || a.includes('people') || a.includes('verified'))) ||
                    (a.includes('подписчик') && (a.includes('лент') || a.includes('времен')));
                if (!looksFollowers) continue;
                const n = el.querySelectorAll('[data-testid="UserCell"]').length;
                if (n > bestCount) {
                    best = el;
                    bestCount = n;
                }
            }
            return bestCount > 0 ? best : primaryEl;
        }

        /** На узкой вёрстке «Who to follow» может быть в primary — отсекаем по заголовку секции. */
        function underWhoToFollowModule(el) {
            let n = el;
            for (let d = 0; d < 12 && n; d++, n = n.parentElement) {
                const h2 = n.querySelector && n.querySelector(':scope > h2');
                if (!h2) continue;
                const t = (h2.textContent || '').trim().toLowerCase();
                if (t.includes('who to follow') || t.includes('кого читать') || t.includes('кому следовать')) {
                    return true;
                }
            }
            return false;
        }

        const listRoot = findFollowersListRoot(primary) || primary;
        let cells;
        if (listRoot) {
            cells = listRoot.querySelectorAll('[data-testid="UserCell"]');
        } else {
            cells = [];
            for (const c of document.querySelectorAll('[data-testid="UserCell"]')) {
                if (sidebar && sidebar.contains(c)) continue;
                cells.push(c);
            }
        }

        for (const cell of cells) {
            if (sidebar && sidebar.contains(cell)) continue;
            if (underWhoToFollowModule(cell)) continue;
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

            const bio = bioFromUserCell(cell, handle);

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
    list_only: bool = False,
    enrich_only: bool = False,
    enrich_usernames: list[str] | None = None,
) -> dict:
    del max_posts_per_follower  # для X не используется (совместимость сигнатуры с TikTok/IG)

    owner = _norm_x_user(owner_username)
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
                lo, hi = _X_MEMBER_PROFILE_GAP_SEC
                await asyncio.sleep(lo + random.random() * (hi - lo))
            row["posts"] = []
            try:
                await _x_enrich_follower_profile_playwright(page, _wu, row)
            except Exception as exc:
                print(
                    f"[audience] x enrich (внешний) @{row.get('username')}: {exc}",
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
            print(f"[audience] x skip_existing: не удалось прочитать БД: {exc}", file=sys.stderr)

    if enrich_only and enrich_usernames:
        want = {str(u or "").strip().lstrip("@").lower() for u in enrich_usernames if str(u or "").strip()}
        if want:
            skip_usernames = {u for u in skip_usernames if u in want}

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
        if enrich_only and skip_usernames and un not in skip_usernames:
            continue
        if skip_existing_member_profiles and skip_usernames and un in skip_usernames:
            d = dict(row)
            d["_reuse_existing"] = True
            followers.append(d)
            continue
        followers.append(dict(row))

    if enrich_only and not followers and skip_usernames:
        return {"error": "Не удалось обновить подписчиков X — список пуст или нет совпадений с БД."}

    if not followers:
        return {
            "error": (
                "Не удалось прочитать список подписчиков X. "
                "Проверьте вход, откройте вручную страницы «Followers» / «Verified followers» "
                "и при необходимости пришлите скрин DOM: предпочтительны селекторы "
                "``[data-testid=\"UserCell\"]`` или короткий CSS от ``main``, а не XPath от корня документа."
            ),
        }

    if list_only:
        out_mode = "list"
    elif enrich_only:
        out_mode = "enrich"
    else:
        out_mode = "full"
    return {"followers": followers, "owner_username": owner, "audience_mode": out_mode}
