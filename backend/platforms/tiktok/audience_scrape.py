"""
Съём списка подписчиков TikTok (Playwright, та же сессия, что и основной worker).

Сценарий как в живом TikTok: открыть профиль /@user → клик по подписи «Followers» / «Подписчики»
в блоке статистики (приоритет), иначе data-e2e="followers" / Playwright по тексту → модалка
follow-info-popup → прокрутка списка и сбор ссылок /@handle.
Затем по очереди открываются страницы подписчиков для постов (как для обычного профиля).

Ожидается авторизованный браузер (storage_state / профиль), иначе список часто пуст.
"""
from __future__ import annotations

import asyncio
import json
import random
import re
import sys
import time
from typing import Any

# Пауза между визитами на профиль подписчика при съёме постов (сек, случайно в диапазоне).
_TT_MEMBER_PROFILE_GAP_SEC = (3.0, 5.0)


def _is_item_list_url(url: str) -> bool:
    url_lower = url.lower()
    return any(p in url_lower for p in (
        "api/post/item_list",
        "api/item_list",
        "api/recommend/item_list",
        "/item_list/",
        "itemlist",
    ))


def _norm_user(u: str) -> str:
    return (u or "").strip().lstrip("@").lower()


async def _tiktok_try_get_owner_sec_uid_from_page(page) -> str:
    """secUid владельца со страницы профиля (для фильтра XHR списка подписчиков)."""
    try:
        sec = await page.evaluate(
            r"""() => {
                try {
                    const el = document.getElementById('__UNIVERSAL_DATA_FOR_REHYDRATION__');
                    if (!el || !el.textContent) return '';
                    const d = JSON.parse(el.textContent);
                    const sc = (d || {}).__DEFAULT_SCOPE__ || {};
                    const ud = sc['webapp.user-detail'];
                    return (ud && ud.userInfo && ud.userInfo.user && ud.userInfo.user.secUid) || '';
                } catch (_) {
                    return '';
                }
            }""",
        )
        return str(sec or "").strip()
    except Exception:
        return ""


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
        f"[audience] tiktok: ожидался профиль @{owner}, сейчас url={page.url!r}",
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
            f"[audience] tiktok: после goto остаёмся вне профиля @{owner_username}, "
            f"url={page.url!r} (раунд {r + 1}/{rounds})",
            file=sys.stderr,
        )
    return bool(pat.search((page.url or "").split("#")[0]))


def _tiktok_audience_relation_url_ok(url: str) -> bool:
    """
    Отфильтровать XHR ленты For You / рекомендаций — иначе в seen попадают чужие авторы.
    """
    u = url.lower()
    if "tiktok" not in u and "musical" not in u:
        return False
    if any(
        b in u
        for b in (
            "recommend",
            "foryou",
            "for_you",
            "explore",
            "suggest",
            "popular",
            "feed/item",
            "browse/video",
        )
    ):
        return False
    if any(
        s in u
        for s in (
            "follower/list",
            "followerlist",
            "fans/list",
            "fanslist",
        )
    ):
        return True
    if "user/list" in u and "follower" in u:
        return True
    if "relation/user" in u and "follower" in u:
        return True
    if "/api/" in u and "follower" in u and "list" in u:
        return True
    return False


def _tiktok_language_timezone_from_user(u: dict) -> tuple[str, str]:
    """Язык и часовой пояс из объекта user/author TikTok (часто пусто в публичных ответах)."""
    if not isinstance(u, dict):
        return "", ""
    lang = ""
    for key in ("language", "lang", "appLanguage"):
        v = u.get(key)
        if isinstance(v, str) and v.strip():
            lang = v.strip()[:32]
            break
    if not lang:
        for nest_key in ("generalUserInfo", "userPageSettings", "profileTab"):
            nested = u.get(nest_key)
            if not isinstance(nested, dict):
                continue
            for key in ("language", "lang"):
                v = nested.get(key)
                if isinstance(v, str) and v.strip():
                    lang = v.strip()[:32]
                    break
            if lang:
                break
    tz = ""
    for key in ("timezoneName", "timeZone", "tzName", "timezone"):
        v = u.get(key)
        if isinstance(v, str) and v.strip():
            tz = v.strip()[:64]
            break
    if not tz:
        nested = u.get("generalUserInfo")
        if isinstance(nested, dict):
            for key in ("timezoneName", "timeZone", "tzName", "timezone"):
                v = nested.get(key)
                if isinstance(v, str) and v.strip():
                    tz = v.strip()[:64]
                    break
    return lang, tz


def _tiktok_user_row_from_api_dict(uobj: dict, owner_username: str) -> dict | None:
    """Один пользователь из элемента списка подписчиков (не вложенные рекомендации)."""
    uid = uobj.get("uniqueId") or uobj.get("unique_id")
    if not isinstance(uid, str) or not uid.strip():
        return None
    u = _norm_user(uid)
    if not u or u == owner_username:
        return None
    sec = str(uobj.get("secUid") or uobj.get("sec_uid") or uobj.get("id") or "")[:160]
    nick = str(uobj.get("nickname") or uobj.get("nickName") or "")[:255]
    av = (
        uobj.get("avatarMedium")
        or uobj.get("avatarLarger")
        or uobj.get("avatarThumb")
        or uobj.get("avatarUri")
        or ""
    )
    if isinstance(av, dict):
        av = str(av.get("urlList", [""])[0] if av.get("urlList") else "")
    av = str(av)[:2048]
    bio = str(uobj.get("signature") or uobj.get("bio") or "")[:2000]
    priv = bool(uobj.get("privateAccount") or uobj.get("secret") or uobj.get("is_private"))
    stats = uobj.get("stats") or uobj.get("statsV2") or {}
    fc = int(stats.get("followerCount") or stats.get("follower_count") or 0)
    fg = int(stats.get("followingCount") or stats.get("following_count") or 0)
    lk = int(stats.get("heartCount") or stats.get("heart") or stats.get("diggCount") or 0)
    lang, tz = _tiktok_language_timezone_from_user(uobj)
    return {
        "username": u,
        "external_id": sec,
        "display_name": nick,
        "avatar_url": av,
        "bio": bio,
        "is_private": priv,
        "follower_count": fc,
        "following_count": fg,
        "like_count": lk,
        "profile_language": lang,
        "timezone_name": tz,
    }


def _tiktok_list_key_is_follower_chunk(key: str) -> bool:
    lk = key.lower()
    for bad in (
        "recommend",
        "suggest",
        "related",
        "search",
        "similar",
        "mutual",
        "popular",
        "visit",
        "browse",
        "discover",
        "following",
        "friend",
    ):
        if bad in lk:
            return False
    if lk in ("userlist", "followers", "followerlist", "follower_list", "user_list", "fanslist", "fans_list"):
        return True
    if "follower" in lk and "list" in lk:
        return True
    return False


def _parse_follower_relation_xhr_rows(data: Any, owner_username: str) -> list[dict]:
    """
    Только массивы userList / followerList на корне и под dict data|result|body|…
    Глубокий обход JSON не делаем — иначе подхватываются вложенные списки (подписчики другого юзера).
    """
    owner_username = _norm_user(owner_username)
    rows: list[dict] = []

    def emit_from_list_item(el: dict) -> None:
        uobj = el.get("user") if isinstance(el.get("user"), dict) else el
        if not isinstance(uobj, dict):
            return
        row = _tiktok_user_row_from_api_dict(uobj, owner_username)
        if row:
            rows.append(row)

    def consume_lists_in_dict(d: dict) -> None:
        for k, v in d.items():
            if not isinstance(v, list) or not v or not isinstance(v[0], dict):
                continue
            if not _tiktok_list_key_is_follower_chunk(k):
                continue
            for el in v:
                if isinstance(el, dict):
                    emit_from_list_item(el)

    def unwrap_payload(obj: Any, depth: int) -> None:
        if depth > 6 or not isinstance(obj, dict):
            return
        consume_lists_in_dict(obj)
        for wrap in ("data", "result", "body", "extra", "payload", "response"):
            inner = obj.get(wrap)
            if isinstance(inner, dict):
                unwrap_payload(inner, depth + 1)

    unwrap_payload(data, 0)
    return rows


async def _tiktok_try_click_followers_word_label(page, owner_username: str) -> bool:
    """
    Шаг 1: клик по видимой подписи «Followers» / «Подписчики» в блоке статистики профиля
    (как у пользователя в браузере), затем по интерактивному предку — открывается модалка.
    """
    owner_username = _norm_user(owner_username)
    try:
        res = await page.evaluate(
            r"""(owner) => {
                const want = (owner || '').toLowerCase();
                const parts = (location.pathname || '').toLowerCase().split('/').filter(Boolean);
                if (!parts.length || !parts[0].startsWith('@')) return 'not_profile_path';
                const handle = parts[0].slice(1);
                if (handle !== want) return 'wrong_profile:' + handle;

                const stats = document.querySelector('[data-e2e="user-stats"]')
                    || document.querySelector('[data-e2e="user-page"]')
                    || document.querySelector('[data-e2e="user-detail"]');
                if (!stats) return 'no_stats';

                const labelRe = /^(followers|подписчики|subscribers|subscriber)$/i;
                const candidates = [];
                stats.querySelectorAll('span, div, p, strong, a, button').forEach((el) => {
                    const raw = (el.textContent || '').replace(/\u200b/g, '').replace(/\s+/g, ' ').trim();
                    if (!raw || raw.length > 40) return;
                    if (!labelRe.test(raw)) return;
                    candidates.push(el);
                });
                if (!candidates.length) return 'no_followers_label';

                let label = candidates[0];
                for (const el of candidates) {
                    if ((el.textContent || '').length < (label.textContent || '').length) label = el;
                }

                let t = label;
                for (let i = 0; i < 14 && t; i++) {
                    const tag = (t.tagName || '').toUpperCase();
                    const role = t.getAttribute('role');
                    const tab = t.getAttribute('tabindex');
                    const cs = window.getComputedStyle(t);
                    if (tag === 'A' || tag === 'BUTTON' || role === 'button' || tab === '0') {
                        t.click();
                        return 'ok_word';
                    }
                    if (cs.cursor === 'pointer' && (tag === 'DIV' || tag === 'SPAN')) {
                        t.click();
                        return 'ok_word_pointer';
                    }
                    t = t.parentElement;
                }
                label.click();
                return 'ok_word_direct';
            }""",
            owner_username,
        )
        if res and str(res).startswith("ok"):
            return True
        print(f"[audience] tiktok click followers word label: {res}", file=sys.stderr)
        return False
    except Exception as exc:
        print(f"[audience] tiktok click followers word label exc: {exc}", file=sys.stderr)
        return False


async def _tiktok_try_click_followers_data_e2e_scoped(page, owner_username: str) -> bool:
    """
    Шаг 2: клик по [data-e2e="followers"] только внутри каркаса страницы этого профиля.
    """
    owner_username = _norm_user(owner_username)
    try:
        res = await page.evaluate(
            r"""(owner) => {
                const want = (owner || '').toLowerCase();
                const parts = (location.pathname || '').toLowerCase().split('/').filter(Boolean);
                if (!parts.length || !parts[0].startsWith('@')) return 'not_profile_path';
                const handle = parts[0].slice(1);
                if (handle !== want) return 'wrong_profile:' + handle;

                const roots = [
                    document.querySelector('[data-e2e="user-page"]'),
                    document.querySelector('[data-e2e="user-detail"]'),
                    document.querySelector('#main-content-others_homepage'),
                ].filter(Boolean);

                let el = null;
                for (const root of roots) {
                    const hit = root.querySelector('[data-e2e="followers"]');
                    if (hit) { el = hit; break; }
                }
                if (!el) {
                    const stats = document.querySelector('[data-e2e="user-stats"]');
                    if (stats) el = stats.querySelector('[data-e2e="followers"]');
                }
                if (!el) {
                    const strongs = Array.from(document.querySelectorAll('[data-e2e="user-page"] strong[title], #main-content-others_homepage strong[title]'));
                    for (const s of strongs) {
                        const t = (s.getAttribute('title') || s.textContent || '').toLowerCase();
                        if (t === 'followers' || t === 'подписчики' || t === 'subscriber' || t === 'subscribers') {
                            el = s;
                            break;
                        }
                    }
                }
                if (!el) {
                    const main = document.querySelector('main');
                    if (main) el = main.querySelector('[data-e2e="followers"]');
                }
                if (!el) return 'no_followers_control';

                let t = el;
                for (let i = 0; i < 10 && t; i++) {
                    const tag = (t.tagName || '').toUpperCase();
                    const role = t.getAttribute('role');
                    if (tag === 'A' || tag === 'BUTTON' || role === 'button' || t.getAttribute('tabindex') === '0') {
                        t.click();
                        return 'ok';
                    }
                    t = t.parentElement;
                }
                el.click();
                return 'ok';
            }""",
            owner_username,
        )
        if res != "ok":
            print(f"[audience] tiktok scoped click followers data-e2e: {res}", file=sys.stderr)
        return res == "ok"
    except Exception as exc:
        print(f"[audience] tiktok click followers data-e2e: {exc}", file=sys.stderr)
        return False


async def _tiktok_try_click_followers_playwright_label(page, owner_username: str) -> bool:
    """Шаг 3: Playwright — точный текст «Followers» / «Подписчики» внутри user-stats."""
    owner_username = _norm_user(owner_username)
    if not _tiktok_profile_url_regex(owner_username).search(page.url or ""):
        return False
    root = page.locator('[data-e2e="user-stats"]').first
    if await root.count() == 0:
        root = page.locator('[data-e2e="user-page"]').first
    if await root.count() == 0:
        return False
    try:
        await root.scroll_into_view_if_needed(timeout=4000)
    except Exception:
        pass
    for pat in (
        re.compile(r"^Followers$", re.I),
        re.compile(r"^Подписчики$", re.I),
        re.compile(r"^Subscribers$", re.I),
    ):
        loc = root.get_by_text(pat).first
        try:
            if await loc.count() > 0:
                await loc.click(timeout=8000)
                return True
        except Exception:
            continue
    return False


async def _tiktok_click_followers_stat_scoped(page, owner_username: str) -> bool:
    """
    Открыть модалку подписчиков: сначала клик по подписи «Followers», затем data-e2e, затем Playwright.
    Глобальный querySelector('[data-e2e="followers"]') без скоупа не используем — ломает ленту.
    """
    if await _tiktok_try_click_followers_word_label(page, owner_username):
        print("[audience] tiktok: followers modal — клик по подписи Followers", file=sys.stderr)
        return True
    if await _tiktok_try_click_followers_data_e2e_scoped(page, owner_username):
        print("[audience] tiktok: followers modal — клик по data-e2e/strong", file=sys.stderr)
        return True
    if await _tiktok_try_click_followers_playwright_label(page, owner_username):
        print("[audience] tiktok: followers modal — клик Playwright по тексту", file=sys.stderr)
        return True
    return False


async def _tiktok_wait_followers_modal(page, timeout_ms: int = 22_000) -> bool:
    try:
        await page.wait_for_selector(
            '[data-e2e="follow-info-popup"], section[role="dialog"][aria-modal="true"]',
            timeout=timeout_ms,
        )
        return True
    except Exception:
        return False


async def _tiktok_followers_modal_switch_off_suggested_tab(page) -> None:
    """
    В модалке часто по умолчанию активна вкладка «Suggested» — кликаем «Followers» / «Подписчики».
    """
    try:
        res = await page.evaluate(
            r"""() => {
                const popup = document.querySelector('[data-e2e="follow-info-popup"]')
                    || document.querySelector('section[role="dialog"][aria-modal="true"]');
                if (!popup) return 'no_popup';
                const reFollow = /^(Followers|Подписчики|Fans)$/i;
                const all = popup.querySelectorAll(
                    '[role="tab"], button, div[class*="Tab"], span[class*="Tab"], div[class*="PCTabs"] span',
                );
                for (const el of all) {
                    const t = (el.textContent || '').trim().split(/\s+/).slice(0, 3).join(' ');
                    if (t.length > 28) continue;
                    if (!reFollow.test(t)) continue;
                    const clickEl = el.closest('[role="tab"]') || el.closest('button') || el;
                    try {
                        clickEl.click();
                        return 'ok';
                    } catch (_) {}
                }
                for (const el of popup.querySelectorAll('button, span, div')) {
                    const t = (el.textContent || '').trim();
                    if (!reFollow.test(t) || t.length > 22) continue;
                    if (el.children.length > 2) continue;
                    try {
                        (el.closest('[role="tab"]') || el.parentElement || el).click();
                        return 'ok_wide';
                    } catch (_) {}
                }
                return 'miss';
            }""",
        )
        if res in ("ok", "ok_wide"):
            print(f"[audience] tiktok: переключение на вкладку подписчиков в модалке ({res})", file=sys.stderr)
            await asyncio.sleep(0.45)
        elif res == "miss":
            popup = page.locator('[data-e2e="follow-info-popup"]').first
            if await popup.count() == 0:
                popup = page.locator('section[role="dialog"][aria-modal="true"]').first
            if await popup.count() > 0:
                for label in ("Followers", "Подписчики", "Fans"):
                    try:
                        loc = popup.get_by_text(label, exact=True).first
                        if await loc.count() > 0:
                            await loc.click(timeout=5000)
                            print(f"[audience] tiktok: вкладка подписчиков (Playwright: {label})", file=sys.stderr)
                            await asyncio.sleep(0.45)
                            break
                    except Exception:
                        continue
            else:
                print(
                    "[audience] tiktok: вкладка Followers/Подписчики в модалке не найдена",
                    file=sys.stderr,
                )
    except Exception as exc:
        print(f"[audience] tiktok modal tab switch: {exc}", file=sys.stderr)


async def _tiktok_close_followers_modal(page) -> None:
    try:
        loc = page.locator('[data-e2e="follow-popup-close"]').first
        if await loc.count() > 0:
            await loc.click(timeout=6000)
            await asyncio.sleep(0.35)
            return
    except Exception:
        pass
    try:
        await page.keyboard.press("Escape")
        await asyncio.sleep(0.25)
    except Exception:
        pass


async def _tiktok_scroll_followers_modal(
    page,
    owner_username: str,
    seen: dict[str, dict],
    limit: int,
) -> None:
    """Прокрутка списка внутри модалки и слияние строк из DOM (ник + аватар из карточки)."""
    stagnant = 0
    prev = -1
    for i in range(90):
        if len(seen) >= limit:
            break
        try:
            rows = await page.evaluate(
                r"""() => {
                    const popup = document.querySelector('[data-e2e="follow-info-popup"]')
                        || document.querySelector('section[role="dialog"][aria-modal="true"]');
                    if (!popup) return [];
                    const listRoot = popup.querySelector('[class*="DivUserListContainer"]')
                        || popup.querySelector('[class*="UserListContainer"]')
                        || popup.querySelector('[class*="DivUserList"]')
                        || popup.querySelector('div[role="list"]')
                        || popup.querySelector('ol');
                    if (!listRoot) return [];
                    const re = /^\/@([a-z0-9._]+)\/?$/i;
                    const out = [];
                    const done = new Set();
                    const underSuggested = (node) => {
                        let x = node;
                        for (let d = 0; d < 18 && x; d++) {
                            const cls = String(x.className || '').toLowerCase();
                            const e2e = String(x.getAttribute('data-e2e') || '').toLowerCase();
                            const lab = String(x.getAttribute('aria-label') || '').toLowerCase();
                            const id = String(x.id || '').toLowerCase();
                            if (cls.includes('suggest') || e2e.includes('suggest') || lab.includes('suggested')
                                || id.includes('suggest')) return true;
                            x = x.parentElement;
                        }
                        return false;
                    };
                    listRoot.querySelectorAll('a[href^="/@"]').forEach(a => {
                        if (underSuggested(a)) return;
                        const href = (a.getAttribute('href') || '').split('?')[0];
                        const m = href.match(re);
                        if (!m) return;
                        const u = m[1].toLowerCase();
                        if (done.has(u)) return;
                        done.add(u);
                        let nick = '';
                        const nickEl = a.querySelector('span[class*="SpanNickname"]')
                            || a.querySelector('[class*="Nickname"]');
                        if (nickEl) nick = (nickEl.textContent || '').trim();
                        if (!nick) {
                            const uidEl = a.querySelector('p[class*="PUniqueId"]')
                                || a.querySelector('[class*="UniqueId"]');
                            if (uidEl) nick = (uidEl.textContent || '').trim();
                        }
                        const img = a.querySelector('img[src]');
                        const av = img ? (img.getAttribute('src') || '') : '';
                        out.push({
                            username: u,
                            display_name: nick.slice(0, 255),
                            avatar_url: av.slice(0, 2048),
                        });
                    });
                    return out;
                }""",
            )
        except Exception as exc:
            print(f"[audience] tiktok modal dom read: {exc}", file=sys.stderr)
            rows = []

        for r in rows or []:
            u = _norm_user(str(r.get("username") or ""))
            if not u or u == owner_username:
                continue
            if u not in seen:
                seen[u] = {
                    "username": u,
                    "external_id": "",
                    "display_name": str(r.get("display_name") or "")[:255],
                    "avatar_url": str(r.get("avatar_url") or "")[:2048],
                    "bio": "",
                    "is_private": False,
                    "follower_count": 0,
                    "following_count": 0,
                    "like_count": 0,
                    "profile_language": "",
                    "timezone_name": "",
                }
            else:
                if not seen[u].get("display_name") and r.get("display_name"):
                    seen[u]["display_name"] = str(r.get("display_name"))[:255]
                if not seen[u].get("avatar_url") and r.get("avatar_url"):
                    seen[u]["avatar_url"] = str(r.get("avatar_url"))[:2048]

            if len(seen) >= limit:
                return

        n = len(seen)
        if n <= prev:
            stagnant += 1
        else:
            stagnant = 0
        prev = n
        if stagnant > 24:
            break

        try:
            await page.evaluate(
                r"""() => {
                    const popup = document.querySelector('[data-e2e="follow-info-popup"]')
                        || document.querySelector('section[role="dialog"][aria-modal="true"]');
                    if (!popup) return;
                    const list = popup.querySelector('[class*="DivUserListContainer"]')
                        || popup.querySelector('[class*="UserListContainer"]')
                        || popup.querySelector('ol')
                        || popup;
                    list.scrollTop += 950;
                }""",
            )
        except Exception:
            # Без модалки колесо крутит ленту For You — не делаем.
            try:
                has_popup = await page.evaluate(
                    "() => !!(document.querySelector('[data-e2e=\"follow-info-popup\"]') "
                    "|| document.querySelector('section[role=\"dialog\"][aria-modal=\"true\"]'))",
                )
            except Exception:
                has_popup = False
            if has_popup:
                await page.mouse.wheel(0, 700)
        await asyncio.sleep(0.28 + (i % 8) * 0.04)


async def _tiktok_open_followers_modal_from_profile(page, _wu, owner_username: str) -> bool:
    profile_url = f"https://www.tiktok.com/@{owner_username}"
    if not await _tiktok_goto_profile_with_redirect_recovery(page, owner_username, profile_url, _wu):
        return False
    await asyncio.sleep(0.45)

    if not await _tiktok_click_followers_stat_scoped(page, owner_username):
        print("[audience] tiktok: не удалось кликнуть по блоку подписчиков на профиле", file=sys.stderr)
        return False
    await asyncio.sleep(0.45)
    if not await _tiktok_wait_followers_modal(page):
        print("[audience] tiktok: модалка подписчиков не открылась", file=sys.stderr)
        return False
    await _tiktok_followers_modal_switch_off_suggested_tab(page)
    return True


async def _tiktok_fallback_retry_followers_modal(
    page,
    _wu,
    owner_username: str,
    seen: dict[str, dict],
    limit: int,
) -> None:
    """
    Повторный заход на /@user и открытие модалки подписчиков.
    Прямой URL /@user/followers в веб-клиенте TikTok не используем — редирект на For You.
    """
    profile_url = f"https://www.tiktok.com/@{owner_username}"
    for attempt in range(4):
        if len(seen) >= limit:
            return
        try:
            if not await _tiktok_goto_profile_with_redirect_recovery(
                page, owner_username, profile_url, _wu, rounds=5, dwell_s=9.0,
            ):
                await asyncio.sleep(0.5 + attempt * 0.15)
                continue
            await asyncio.sleep(0.45 + attempt * 0.12)
            if not await _tiktok_click_followers_stat_scoped(page, owner_username):
                print(
                    f"[audience] tiktok fallback modal: клик подписчиков не удался (попытка {attempt + 1}/4)",
                    file=sys.stderr,
                )
                continue
            await asyncio.sleep(0.45)
            if not await _tiktok_wait_followers_modal(page):
                print(
                    f"[audience] tiktok fallback modal: попап не открылся (попытка {attempt + 1}/4)",
                    file=sys.stderr,
                )
                continue
            await _tiktok_followers_modal_switch_off_suggested_tab(page)
            await _tiktok_scroll_followers_modal(page, owner_username, seen, limit)
            await _tiktok_close_followers_modal(page)
            return
        except Exception as exc:
            print(f"[audience] tiktok fallback modal: {exc}", file=sys.stderr)


async def scrape_tiktok_audience_followers(
    page,
    _wu,
    owner_username: str,
    limit: int,
    *,
    max_posts_per_follower: int = 35,
    skip_existing_member_profiles: bool = False,
    audience_account_id: int | None = None,
) -> dict:
    owner_username = _norm_user(owner_username)
    if not owner_username:
        return {"error": "Пустой username"}

    limit = max(1, min(int(limit or 100), 500))
    seen: dict[str, dict] = {}
    owner_sec_ref: list[str] = [""]

    async def on_response(response):
        try:
            sec = owner_sec_ref[0]
            if not sec:
                return
            url = response.url
            if response.status != 200:
                return
            if not _tiktok_audience_relation_url_ok(url):
                return
            sl = sec.lower()
            try:
                req = response.request
                req_url = (req.url or "").lower() if req else ""
                post_data = ""
                if req and req.post_data:
                    post_data = str(req.post_data).lower()
            except Exception:
                req_url = ""
                post_data = ""
            su = url.lower()
            if sl not in req_url and sl not in su and sl not in post_data:
                return
            body = await response.body()
            if not body:
                return
            data = json.loads(body.decode("utf-8", errors="replace"))
            rows = _parse_follower_relation_xhr_rows(data, owner_username)
            for r in rows:
                u = r.get("username")
                if not u or u == owner_username:
                    continue
                if u not in seen:
                    seen[u] = r
                else:
                    if not seen[u].get("external_id") and r.get("external_id"):
                        seen[u]["external_id"] = r["external_id"]
                    if not seen[u].get("display_name") and r.get("display_name"):
                        seen[u]["display_name"] = r["display_name"]
                    if not (seen[u].get("profile_language") or "").strip() and (r.get("profile_language") or "").strip():
                        seen[u]["profile_language"] = r["profile_language"]
                    if not (seen[u].get("timezone_name") or "").strip() and (r.get("timezone_name") or "").strip():
                        seen[u]["timezone_name"] = r["timezone_name"]
        except Exception as exc:
            print(f"[audience] tiktok on_response: {exc}", file=sys.stderr)

    page.on("response", on_response)
    try:
        profile_url = f"https://www.tiktok.com/@{owner_username}"
        if await _tiktok_goto_profile_with_redirect_recovery(
            page, owner_username, profile_url, _wu, rounds=2, dwell_s=5.0,
        ):
            owner_sec_ref[0] = (await _tiktok_try_get_owner_sec_uid_from_page(page) or "").strip()
        if not owner_sec_ref[0]:
            print(
                "[audience] tiktok: secUid владельца не найден — XHR подписчиков отключён, только DOM модалки",
                file=sys.stderr,
            )

        modal_ok = await _tiktok_open_followers_modal_from_profile(page, _wu, owner_username)
        if modal_ok:
            await _tiktok_scroll_followers_modal(page, owner_username, seen, limit)
            await _tiktok_close_followers_modal(page)

        if len(seen) < limit:
            await _tiktok_fallback_retry_followers_modal(page, _wu, owner_username, seen, limit)
    finally:
        try:
            page.remove_listener("response", on_response)
        except Exception:
            pass

    followers = list(seen.values())[:limit]

    skip_usernames: set[str] = set()
    if skip_existing_member_profiles and audience_account_id:
        try:
            from platforms.audience_skip import existing_audience_usernames_for_dashboard_account

            # ORM только из sync-контекста (иначе Django 5 — SynchronousOnlyOperation, сет пустой).
            skip_usernames = await asyncio.to_thread(
                existing_audience_usernames_for_dashboard_account,
                int(audience_account_id),
            )
        except Exception as exc:
            print(f"[audience] tiktok skip_existing: не удалось прочитать БД: {exc}", file=sys.stderr)

    _mpp = max_posts_per_follower if max_posts_per_follower is not None else 35
    max_posts = max(0, min(int(_mpp), 80))
    member_visit_i = 0
    for row in followers:
        u_n = _norm_user(str(row.get("username") or ""))
        if skip_existing_member_profiles and skip_usernames and u_n and u_n in skip_usernames:
            row["_reuse_existing"] = True
            row["posts"] = []
            continue
        if row.get("is_private") or max_posts <= 0:
            row["posts"] = []
            continue
        if member_visit_i > 0:
            lo, hi = _TT_MEMBER_PROFILE_GAP_SEC
            await asyncio.sleep(lo + random.random() * (hi - lo))
        member_visit_i += 1
        u = row.get("username")
        posts, post_meta = await _scrape_tiktok_member_posts_short(page, _wu, u, max_posts)
        row["posts"] = posts
        for k in ("profile_language", "timezone_name"):
            v = (post_meta or {}).get(k)
            if v and not (row.get(k) or "").strip():
                row[k] = v

    return {"followers": followers, "owner_username": owner_username}


async def _scrape_tiktok_member_posts_short(
    page, _wu, username: str, max_posts: int,
) -> tuple[list[dict], dict[str, str]]:
    username = _norm_user(username)
    empty_meta = {"profile_language": "", "timezone_name": ""}
    if not username:
        return [], empty_meta
    if max_posts <= 0:
        return [], empty_meta
    items: list[dict] = []
    author_snips: list[dict] = []

    async def on_response(response):
        try:
            if not _is_item_list_url(response.url):
                return
            if response.status != 200:
                return
            body = await response.body()
            if not body:
                return
            result = json.loads(body.decode("utf-8", errors="replace"))
            for it in result.get("itemList") or []:
                if not isinstance(it, dict):
                    continue
                author = it.get("author") or {}
                au = _norm_user(str(author.get("uniqueId") or ""))
                if au != username:
                    continue
                if isinstance(author, dict) and len(author_snips) < 8:
                    author_snips.append(author)
                vid = str(it.get("id") or "")
                if not vid:
                    continue
                stats = it.get("stats") or {}
                items.append({
                    "external_id": vid,
                    "description": str(it.get("desc") or "")[:2000],
                    "thumbnail_url": str((it.get("video") or {}).get("cover") or "")[:2048],
                    "post_url": f"https://www.tiktok.com/@{username}/video/{vid}",
                    "view_count": int(stats.get("playCount") or 0),
                    "like_count": int(stats.get("diggCount") or 0),
                    "comment_count": int(stats.get("commentCount") or 0),
                    "share_count": int(stats.get("shareCount") or 0),
                    "posted_at": None,
                })
        except Exception:
            pass

    page.on("response", on_response)
    try:
        prof = f"https://www.tiktok.com/@{username}"
        if not await _tiktok_goto_profile_with_redirect_recovery(
            page, username, prof, _wu, rounds=4, dwell_s=9.0,
        ):
            print(f"[audience] tiktok posts: не профиль @{username}, url={page.url!r}", file=sys.stderr)
        prof_pat = _tiktok_profile_url_regex(username)
        for _ in range(12):
            if len(items) >= max_posts:
                break
            cur = (page.url or "").split("#")[0]
            if not prof_pat.search(cur):
                await _tiktok_goto_profile_with_redirect_recovery(
                    page, username, prof, _wu, rounds=3, dwell_s=6.0,
                )
            await page.mouse.wheel(0, 700)
            await asyncio.sleep(0.45)
    except Exception as exc:
        print(f"[audience] tiktok posts @{username}: {exc}", file=sys.stderr)
    finally:
        try:
            page.remove_listener("response", on_response)
        except Exception:
            pass

    by_id: dict[str, dict] = {}
    for p in items:
        eid = p.get("external_id")
        if eid:
            by_id[eid] = p
    posts_out = list(by_id.values())[:max_posts]
    meta = {"profile_language": "", "timezone_name": ""}
    for ad in author_snips:
        l, t = _tiktok_language_timezone_from_user(ad)
        if l and not meta["profile_language"]:
            meta["profile_language"] = l
        if t and not meta["timezone_name"]:
            meta["timezone_name"] = t
        if meta["profile_language"] and meta["timezone_name"]:
            break
    return posts_out, meta
