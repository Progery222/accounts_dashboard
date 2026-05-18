"""
Список подписчиков Instagram: Playwright только для модалки со списком логинов.

В режиме ``full`` по каждому подписчику — HTTP (см. `audience_member_http.py`).
В режиме ``enrich`` — переход на профиль в Chromium (видимый в окне worker).
Посты подписчиков не собираются (`posts` всегда []).

Политика URL модалки — без программного перехода на /followers/; см. `audience_followers_modal.py`.

Логика модалки: `audience_followers_modal.py`. Профиль/Reels в worker: `worker.py`.
"""
from __future__ import annotations

import asyncio
import random
import sys
import time

from platforms.instagram.audience_followers_modal import (
    ig_followers_dialog_present,
    ig_open_followers_modal_from_profile,
    ig_scroll_followers_modal,
    ig_wait_follower_user_links_in_dialog,
    norm_ig_username as _norm_user,
)
from platforms.instagram.audience_member_http import (
    build_instagram_http_client_from_playwright_page,
    fetch_instagram_member_profile_http,
)

# Случайная пауза между открытием профилей подписчиков (сек, снижает триггер антибота).
_IG_MEMBER_PROFILE_GAP_SEC = (3.0, 5.0)
_IG_ENRICH_PROFILE_DWELL_SEC = (2.5, 4.5)


async def _instagram_enrich_follower_profile_playwright(page, _wu, row: dict) -> None:
    """Открыть профиль подписчика в Chromium (видимый переход), обновить поля строки."""
    from platforms.instagram.audience_member_http import (
        ig_extract_profile_counts_from_page,
        ig_merge_profile_snap_from_http,
        ig_wait_profile_stats,
        parse_instagram_profile_html,
    )

    member_username = _norm_user(str(row.get("username") or ""))
    if not member_username:
        return
    profile_url = f"https://www.instagram.com/{member_username}/"
    print(f"[audience] ig enrich: открываем @{member_username}", file=sys.stderr)
    try:
        await page.bring_to_front()
    except Exception:
        pass
    await page.goto(profile_url, wait_until="load", timeout=90_000)
    if _wu is not None and hasattr(_wu, "wait_for_anti_bot_clear"):
        await _wu.wait_for_anti_bot_clear(page, platform="instagram")
    await ig_wait_profile_stats(page)
    lo, hi = _IG_ENRICH_PROFILE_DWELL_SEC
    await asyncio.sleep(lo + random.random() * (hi - lo))
    url_l = (page.url or "").lower()
    if "accounts/login" in url_l or "challenge" in url_l:
        print(f"[audience] ig enrich @{member_username}: требуется вход", file=sys.stderr)
        row["_enrich_ok"] = False
        row["_enrich_note"] = "Требуется вход в Instagram"
        return
    try:
        html = await page.content()
    except Exception as exc:
        print(f"[audience] ig enrich @{member_username}: {exc}", file=sys.stderr)
        row["_enrich_ok"] = False
        row["_enrich_note"] = str(exc)[:200]
        return
    snap = parse_instagram_profile_html(html)
    for _ in range(3):
        dom_counts = await ig_extract_profile_counts_from_page(page)
        if int(snap.get("follower_count") or 0) <= 0 and dom_counts.get("followers", 0) > 0:
            snap["follower_count"] = dom_counts["followers"]
        if int(snap.get("following_count") or 0) <= 0 and dom_counts.get("following", 0) > 0:
            snap["following_count"] = dom_counts["following"]
        if int(snap.get("follower_count") or 0) > 0 and int(snap.get("following_count") or 0) > 0:
            break
        await page.wait_for_timeout(900)
    if int(snap.get("follower_count") or 0) <= 0 or int(snap.get("following_count") or 0) <= 0:
        snap = await ig_merge_profile_snap_from_http(page, member_username, snap)
    print(
        f"[audience] ig enrich @{member_username}: followers={snap.get('follower_count')} "
        f"following={snap.get('following_count')} url={page.url!r}",
        file=sys.stderr,
    )
    if snap.get("_auth_required"):
        row["_enrich_ok"] = False
        row["_enrich_note"] = "Требуется вход в Instagram"
        return
    if not snap.get("_ok"):
        print(
            f"[audience] ig enrich @{member_username}: слабый разбор "
            f"(status={snap.get('_http_status')!r} err={snap.get('_error')!r})",
            file=sys.stderr,
        )
        row["_enrich_ok"] = False
        row["_enrich_note"] = str(snap.get("_error") or "Слабый разбор страницы")[:200]
    else:
        has_counts = int(snap.get("follower_count") or 0) > 0 or int(snap.get("following_count") or 0) > 0
        row["_enrich_ok"] = bool(has_counts or snap.get("display_name") or snap.get("bio"))
        row["_enrich_note"] = "" if row["_enrich_ok"] else "Имя есть, счётчики не распознаны"
    row["display_name"] = str(snap.get("display_name") or row.get("display_name") or "")[:255]
    row["avatar_url"] = str(snap.get("avatar_url") or row.get("avatar_url") or "")[:2048]
    row["bio"] = str(snap.get("bio") or row.get("bio") or "")[:4000]
    row["follower_count"] = int(snap.get("follower_count") or row.get("follower_count") or 0)
    row["following_count"] = int(snap.get("following_count") or row.get("following_count") or 0)
    row["like_count"] = int(snap.get("like_count") or row.get("like_count") or 0)
    snap_priv = bool(snap.get("is_private"))
    row["is_private"] = snap_priv or bool(row.get("is_private"))


async def _ig_profile_followers_count(page) -> int:
    """Число подписчиков из шапки профиля (как в worker._extract_profile_counts_from_dom)."""
    stats = await page.evaluate(
        r"""
        (() => {
            const toInt = (raw) => {
                const s = String(raw || '').replace(/\u00a0|\u202f|\s/g, '').replace(/,/g, '');
                const m = s.match(/^([\d]+(?:\.[\d]+)?)([kmb])?$/i);
                if (!m) {
                    const d = s.replace(/[^\d]/g, '');
                    return d ? parseInt(d, 10) : 0;
                }
                const n = parseFloat(m[1]);
                const suf = (m[2] || '').toLowerCase();
                const mul = suf === 'k' ? 1e3 : suf === 'm' ? 1e6 : suf === 'b' ? 1e9 : 1;
                return Math.round(n * mul);
            };
            const out = { followers: 0 };
            try {
                const root = document.querySelector('header') || document;
                const readTitleNum = (sel) => {
                    const el = root.querySelector(sel);
                    if (!el) return 0;
                    const t = el.getAttribute('title') || el.textContent || '';
                    return toInt(t);
                };
                const followersByLink =
                    readTitleNum('a[href*="/followers"] span[title]') ||
                    readTitleNum('a[href$="/followers/"] span[title]') ||
                    readTitleNum('section a[href*="/followers"] span[title]');
                if (followersByLink > 0) out.followers = followersByLink;

                const items = Array.from(document.querySelectorAll('header section ul li, section ul li'));
                for (const li of items) {
                    const txt = (li.textContent || '').replace(/\s+/g, ' ').trim();
                    if (!txt) continue;
                    const m = txt.match(/([\d.,]+\s*[KMBkmb]?)/);
                    const val = m ? toInt(m[1]) : 0;
                    const low = txt.toLowerCase();
                    if (!out.followers && /(followers?|подписчик)/i.test(low)) out.followers = val;
                }
                if (!out.followers) {
                    const text = (root.innerText || '').replace(/\s+/g, ' ');
                    const mf = text.match(/([\d.,]+\s*[KMBkmb]?)\s+followers?/i);
                    if (mf) out.followers = toInt(mf[1]);
                }
            } catch (_) {}
            return out;
        })()
        """,
    )
    if not isinstance(stats, dict):
        return 0
    return max(0, int(stats.get("followers") or 0))


async def _ig_open_followers_modal_resilient(page, _wu, owner_username: str, profile_url: str) -> str:
    """
    Открыть модалку подписчиков без программного перехода на /followers/.
    Если после клика оказались на /followers/ без модалки — возврат на профиль и повтор.
    """
    owner_l = owner_username.lower()
    last_how = ""
    for attempt in range(3):
        url_now = (page.url or "").lower()
        if "/followers" in url_now and owner_l in url_now and not await ig_followers_dialog_present(page):
            print(
                f"[audience] ig: URL /followers/ без модалки — возврат на профиль (попытка {attempt + 1})",
                file=sys.stderr,
            )
            await page.goto(profile_url, wait_until="domcontentloaded", timeout=60_000)
            if _wu is not None and hasattr(_wu, "wait_for_anti_bot_clear"):
                await _wu.wait_for_anti_bot_clear(page, platform="instagram")
            await page.wait_for_timeout(1600 + attempt * 450)
        last_how = await ig_open_followers_modal_from_profile(page, owner_username)
        if await ig_followers_dialog_present(page):
            return last_how
        await page.wait_for_timeout(750)
    return last_how


async def scrape_instagram_audience_followers(
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
    _ = max_posts_per_follower  # совместимость worker API; посты подписчиков не собираем
    owner_username = _norm_user(owner_username)
    if not owner_username:
        return {"error": "Пустой username"}
    if enrich_only and not audience_account_id:
        return {"error": "Режим enrich требует audience_account_id."}

    limit = max(1, min(int(limit or 100), 500))
    seen: dict[str, dict] = {}

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
        if list_only:
            return {
                "followers": followers,
                "owner_username": owner_username,
                "audience_mode": "list",
            }
        profile_visits = 0
        for row in followers:
            if profile_visits > 0:
                lo, hi = _IG_MEMBER_PROFILE_GAP_SEC
                await asyncio.sleep(lo + random.random() * (hi - lo))
            profile_visits += 1
            row["posts"] = []
            try:
                await _instagram_enrich_follower_profile_playwright(page, _wu, row)
            except Exception as exc:
                print(
                    f"[audience] ig enrich (внешний) @{row.get('username')}: {exc}",
                    file=sys.stderr,
                )
        return {
            "followers": followers,
            "owner_username": owner_username,
            "audience_mode": "enrich",
        }

    profile_url = f"https://www.instagram.com/{owner_username}/"
    await page.goto(profile_url, wait_until="domcontentloaded", timeout=60_000)
    if _wu is not None and hasattr(_wu, "wait_for_anti_bot_clear"):
        await _wu.wait_for_anti_bot_clear(page, platform="instagram")

    url_l = (page.url or "").lower()
    if "accounts/login" in url_l or "challenge" in url_l:
        return {
            "error": (
                "Instagram требует авторизации — войдите в аккаунт в настройках браузера worker и повторите."
            ),
        }

    await page.wait_for_timeout(2300)

    header_followers = await _ig_profile_followers_count(page)
    effective_cap = min(limit, header_followers) if header_followers > 0 else limit
    if header_followers > 0:
        print(
            f"[audience] ig: в шапке followers={header_followers}, собираем не более {effective_cap}",
            file=sys.stderr,
        )

    how = await _ig_open_followers_modal_resilient(page, _wu, owner_username, profile_url)
    if not await ig_followers_dialog_present(page):
        print(
            f"[audience] ig: модалка подписчиков не открылась после попыток (последний лог: {how})",
            file=sys.stderr,
        )

    if not await ig_wait_follower_user_links_in_dialog(page, owner_username, timeout_ms=28_000):
        return {
            "error": (
                "Не удалось открыть список подписчиков Instagram в модальном окне. "
                "Откройте профиль вручную, нажмите «подписчики» и убедитесь, что появляется окно со списком; "
                "проверьте вход в аккаунт в браузере worker."
            ),
        }

    stagnant = 0
    prev = 0
    for i in range(80):
        if len(seen) >= effective_cap:
            break
        try:
            handles = await page.evaluate(
                r"""(args) => {
                  const o = (args.owner || '').toLowerCase();
                  const cap = Math.max(1, Math.min(parseInt(args.cap, 10) || 500, 500));
                  const dialog = document.querySelector('div[role="dialog"]');
                  if (!dialog) return [];
                  const root = dialog;

                  const isSuggestedHeading = (el) => {
                    const t = (el.textContent || '').replace(/\s+/g, ' ').trim().toLowerCase();
                    if (!t || t.length > 120) return false;
                    const phrases = [
                      'suggested for you',
                      'suggestions for you',
                      'similar accounts',
                      'people you may know',
                      'рекомендации',
                      'рекомендуемые',
                      'вам может понравиться',
                      'sugerencias para ti',
                      'vorschläge für dich',
                      'suggestions pour vous',
                      'sugestões para você',
                      'suggerimenti per te',
                    ];
                    for (const p of phrases) {
                      if (t === p || (t.startsWith(p) && t.length < p.length + 30)) return true;
                    }
                    if (t.includes('suggested for you') || t.includes('suggestions for you')) return true;
                    return false;
                  };

                  let marker = null;
                  root.querySelectorAll('span, div, h2, h3, li, p').forEach((el) => {
                    if (marker) return;
                    if (isSuggestedHeading(el)) marker = el;
                  });

                  const isUserHref = (href) => {
                    const h = (href || '').split('?')[0];
                    const m = h.match(/^\/([^\/]+)\/?$/);
                    if (!m) return null;
                    const u = m[1].toLowerCase();
                    if (
                      !u ||
                      u === o ||
                      ['p', 'reel', 'stories', 'explore', 'accounts', 'legal'].includes(u)
                    ) {
                      return null;
                    }
                    return u;
                  };

                  const beforeSuggested = (a) => {
                    if (!marker) return true;
                    const rel = marker.compareDocumentPosition(a);
                    if (rel & Node.DOCUMENT_POSITION_FOLLOWING) return false;
                    if (rel & Node.DOCUMENT_POSITION_CONTAINED_BY) return false;
                    return true;
                  };

                  const out = [];
                  const seenU = new Set();
                  root.querySelectorAll('a[href]').forEach((a) => {
                    if (out.length >= cap) return;
                    if (!beforeSuggested(a)) return;
                    const u = isUserHref(a.getAttribute('href'));
                    if (!u || seenU.has(u)) return;
                    seenU.add(u);
                    let el = a;
                    let blob = '';
                    for (let depth = 0; depth < 8 && el; depth++) {
                      blob += ' ' + ((el.innerText || '').toLowerCase());
                      el = el.parentElement;
                    }
                    const priv =
                      /\bprivate\b/.test(blob) ||
                      blob.includes('закрыт') ||
                      blob.includes('privé') ||
                      blob.includes('privat');
                    out.push({ username: u, is_private_hint: priv });
                  });
                  return out;
                }""",
                {"owner": owner_username, "cap": effective_cap},
            )
            seen.clear()
            for row in handles or []:
                u = _norm_user(row.get("username") or "")
                if not u or u == owner_username:
                    continue
                seen[u] = {
                    "username": u,
                    "external_id": "",
                    "display_name": "",
                    "avatar_url": "",
                    "bio": "",
                    "is_private": bool(row.get("is_private_hint")),
                    "follower_count": 0,
                    "following_count": 0,
                    "like_count": 0,
                    "profile_language": "",
                    "timezone_name": "",
                }
        except Exception as exc:
            print(f"[audience] ig eval: {exc}", file=sys.stderr)

        if len(seen) <= prev:
            stagnant += 1
        else:
            stagnant = 0
        prev = len(seen)
        if stagnant > 22:
            break
        if len(seen) >= effective_cap:
            break

        await ig_scroll_followers_modal(page)
        await asyncio.sleep(0.35 + (i % 4) * 0.05)

    followers = list(seen.values())[:effective_cap]

    if list_only:
        for row in followers:
            row["posts"] = []
        return {
            "followers": followers,
            "owner_username": owner_username,
            "audience_mode": "list",
        }

    skip_usernames: set[str] = set()
    if skip_existing_member_profiles and audience_account_id:
        try:
            from platforms.audience_skip import existing_audience_usernames_for_dashboard_account

            skip_usernames = await asyncio.to_thread(
                existing_audience_usernames_for_dashboard_account,
                int(audience_account_id),
            )
        except Exception as exc:
            print(f"[audience] ig skip_existing: не удалось прочитать БД: {exc}", file=sys.stderr)

    http_client = await build_instagram_http_client_from_playwright_page(page)
    if http_client is None:
        print(
            "[audience] ig: не удалось собрать HTTP-клиент из сессии браузера — "
            "поля подписчиков будут частично пустыми (остаётся username из модалки).",
            file=sys.stderr,
        )

    try:
        profile_visits = 0
        for row in followers:
            u_n = _norm_user(str(row.get("username") or ""))
            if skip_existing_member_profiles and skip_usernames and u_n and u_n in skip_usernames:
                row["_reuse_existing"] = True
                row["posts"] = []
                continue
            if profile_visits > 0:
                lo, hi = _IG_MEMBER_PROFILE_GAP_SEC
                await asyncio.sleep(lo + random.random() * (hi - lo))
            profile_visits += 1
            u = row.get("username")
            row["posts"] = []
            snap: dict = {}
            if http_client is not None:
                snap = await fetch_instagram_member_profile_http(
                    http_client,
                    str(u or ""),
                    timeout_sec=28.0,
                )
                if not snap.get("_ok"):
                    print(
                        f"[audience] ig http: слабый разбор @{u} "
                        f"(status={snap.get('_http_status')!r} err={snap.get('_error')!r})",
                        file=sys.stderr,
                    )
            row["display_name"] = str(snap.get("display_name") or row.get("display_name") or "")[:255]
            row["avatar_url"] = str(snap.get("avatar_url") or row.get("avatar_url") or "")[:2048]
            row["bio"] = str(snap.get("bio") or row.get("bio") or "")[:4000]
            row["follower_count"] = int(snap.get("follower_count") or 0)
            row["following_count"] = int(snap.get("following_count") or 0)
            row["like_count"] = int(snap.get("like_count") or 0)
            snap_priv = bool(snap.get("is_private"))
            row["is_private"] = snap_priv or bool(row.get("is_private"))
    finally:
        if http_client is not None:
            await http_client.aclose()

    return {"followers": followers, "owner_username": owner_username, "audience_mode": "full"}
