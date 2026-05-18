"""
Playwright subprocess worker for TikTok video list.

Server mode  (BROWSER_HEADLESS=true):
  Uses a storage_state JSON file (BROWSER_STATE_FILE) with exported cookies.
  Run `python manage.py setup_tiktok_auth` once to log in and export the file.

Local dev mode (BROWSER_HEADLESS=false or not set):
    Uses a persistent Chromium profile at BROWSER_PROFILE_DIR
    (auto-detected cross-platform default if not set).
    Shows browser window so you can log in manually once.

Демон (``--daemon``): по умолчанию окно не закрывается при окончании stdin — см.
``WORKER_AUTOCLOSE_BROWSER_ON_EXIT`` в ``platforms/worker_utils.py``.
"""
import asyncio
import json
import os
import re
import sys
from pathlib import Path
from platforms.profile_unavailable import PROFILE_UNAVAILABLE_MARK


def _default_profile_dir() -> str:
    home = Path.home()
    if (home / "AppData").exists():  # Windows
        return str(home / "AppData" / "Local" / "TikStatsChromeProfile")
    return str(home / ".config" / "tikstats-chrome-profile")  # Linux / macOS


HEADLESS = os.environ.get("BROWSER_HEADLESS", "false").lower() == "true"
PROFILE_DIR = os.environ.get("BROWSER_PROFILE_DIR", "") or _default_profile_dir()
STATE_FILE = os.environ.get("BROWSER_STATE_FILE", "")


def _cleanup_chrome_artifacts(profile_dir: str) -> None:
    """
    Remove stale CHROME_DELETE / Snapshots artefacts that prevent Chrome from starting.

    When Chrome detects a version downgrade it moves parts of the profile into
    ``<profile>.CHROME_DELETE`` / ``Snapshots.CHROME_DELETE`` backup folders.
    If that move fails (e.g. destination already exists), Chrome exits with
    code 33 and refuses to start on every subsequent run until the artefacts
    are removed.  Deleting them lets Chrome start fresh from the still-intact
    ``Default/`` directory.
    """
    import shutil
    base = Path(profile_dir)
    removed = []
    for entry in base.iterdir():
        if entry.name.endswith(".CHROME_DELETE") or entry.name == "Snapshots":
            try:
                shutil.rmtree(entry, ignore_errors=True)
                removed.append(entry.name)
            except Exception as exc:
                print(f"[worker] cleanup: could not remove {entry.name}: {exc}", file=sys.stderr)
    if removed:
        print(f"[worker] cleaned up Chrome artefacts: {removed}", file=sys.stderr)


def _is_item_list_url(url: str) -> bool:
    """Return True for any TikTok video-list API endpoint."""
    url_lower = url.lower()
    return any(p in url_lower for p in (
        "api/post/item_list",
        "api/item_list",
        "api/recommend/item_list",
        "/item_list/",
        "itemlist",
    ))


async def _page_indicates_profile_unavailable(page) -> bool:
    try:
        return bool(await page.evaluate(
            """() => {
                const t = ((document.body && document.body.innerText) || '').toLowerCase();
                return (
                    t.includes("couldn't find this account") ||
                    t.includes("could not find this account") ||
                    t.includes("account not found") ||
                    t.includes("профиль не найден") ||
                    t.includes("аккаунт не найден")
                );
            }"""
        ))
    except Exception:
        return False


def _item_list_key(it: dict) -> str:
    if not isinstance(it, dict):
        return ""
    return str(it.get("id") or it.get("aweme_id") or "").strip()


def _uniq_items_count(items: list) -> int:
    keys = set()
    for it in items:
        k = _item_list_key(it)
        if k:
            keys.add(k)
    return len(keys)


def _dedupe_item_list(items: list) -> list[dict]:
    seen: dict[str, dict] = {}
    order: list[str] = []
    for it in items:
        k = _item_list_key(it)
        if not k:
            continue
        if k not in seen:
            seen[k] = it
            order.append(k)
    return [seen[k] for k in order]


async def _run_with_context(
    data: dict,
    context,
    _wu,
    state_path: Path | None,
    page=None,
) -> dict:
    data = dict(data)
    if data.get("audience_followers"):
        from platforms.tiktok.audience_scrape import scrape_tiktok_audience_followers

        username = (data.get("username") or "").lstrip("@").strip().lower()
        lim = int(data.get("limit") or 100)
        _mpp = data.get("max_posts_per_follower")
        mpp = int(_mpp) if _mpp is not None else 35
        if not username:
            return {"error": "Не указан username для съёма подписчиков."}
        own_page = page is None
        if page is None:
            page = await context.new_page()
        try:
            _raw_aid = data.get("audience_account_id")
            audience_account_id = int(_raw_aid) if _raw_aid is not None else None
            return await scrape_tiktok_audience_followers(
                page, _wu, username, lim,
                max_posts_per_follower=mpp,
                skip_existing_member_profiles=bool(data.get("skip_existing_member_profiles")),
                audience_account_id=audience_account_id,
                list_only=bool(data.get("list_only")),
                enrich_only=bool(data.get("enrich_only")),
                enrich_usernames=data.get("enrich_usernames"),
            )
        finally:
            if own_page:
                await page.close()

    url: str = data["url"]
    m_user = re.search(r"/@([^/?#]+)", url)
    profile_username = m_user.group(1).strip().lower() if m_user else ""
    target_post_count = int(data.get("target_post_count") or 0)
    collected: list[dict] = []
    profile_stats: dict = {}
    own_page = page is None
    if page is None:
        page = await context.new_page()
    try:

            # ── Event-listener approach: capture ALL matching responses ──────
            # Using page.on("response") instead of expect_response() avoids
            # race conditions where the XHR fires before the context manager
            # is fully set up, and handles cases where TikTok uses a slightly
            # different URL pattern.
            items_captured: list[dict] = []
            all_item_urls: list[str] = []

            async def on_response(response):
                try:
                    resp_url = response.url
                    if not _is_item_list_url(resp_url):
                        return
                    all_item_urls.append(resp_url)
                    status = response.status
                    if status != 200:
                        print(f"[worker] item_list url={resp_url[:80]!r} status={status} — skipping", file=sys.stderr)
                        return
                    body = await response.body()
                    if not body:
                        print(
                            f"[worker] item_list url={resp_url[:80]!r} — пустой ответ "
                            "(TikTok требует авторизации; войдите в Настройках → TikTok)",
                            file=sys.stderr,
                        )
                        return
                    result = json.loads(body)
                    items = result.get("itemList") or []
                    if profile_username:
                        filtered_items = []
                        for it in items:
                            author = it.get("author", {}) if isinstance(it, dict) else {}
                            a_user = str(author.get("uniqueId") or "").strip().lower()
                            if a_user == profile_username:
                                filtered_items.append(it)
                        items = filtered_items
                    status_code = result.get("statusCode", "?")
                    login_required = result.get("status_code") == 10102 or "login" in str(result.get("extra", {})).lower()
                    if login_required:
                        print("[worker] TikTok вернул код требования авторизации", file=sys.stderr)
                        return
                    print(
                        f"[worker] item_list url={resp_url[:80]!r} "
                        f"statusCode={status_code} items={len(items)}",
                        file=sys.stderr,
                    )
                    if items:
                        items_captured.extend(items)
                except Exception as exc:
                    print(f"[worker] on_response error ({type(exc).__name__}): {exc}", file=sys.stderr)

            page.on("response", on_response)

            # Navigate to the profile page (без двойного goto: сразу стабилизация URL)
            if profile_username and "/@" in (url or ""):
                from platforms.tiktok.audience_scrape import _tiktok_goto_profile_with_redirect_recovery

                u0 = url.split("#")[0]
                if not await _tiktok_goto_profile_with_redirect_recovery(
                    page, profile_username, u0, _wu, rounds=4, dwell_s=9.0,
                ):
                    print(
                        f"[tiktok_worker] не удалось удержать страницу профиля @{profile_username}, "
                        f"url={page.url!r}",
                        file=sys.stderr,
                    )
            else:
                await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
                if _wu is not None and hasattr(_wu, "wait_for_anti_bot_clear"):
                    await _wu.wait_for_anti_bot_clear(page, platform="tiktok")

            # Read profile counters from rendered header (small accounts often
            # have missing SSR stats but visible UI counters).
            try:
                profile_stats = await page.evaluate(
                    r"""() => {
                        const out = { follower_text: "", following_text: "", like_text: "", avatar_url: "" };
                        try {
                            const avatarMeta = document.querySelector('meta[property="og:image"]');
                            const avatarFromMeta = (avatarMeta?.getAttribute("content") || "").trim();
                            if (avatarFromMeta) out.avatar_url = avatarFromMeta;
                        } catch (_) {}
                        // Do not bind follower count to the "first stat" selector:
                        // TikTok header order is usually Following / Followers / Likes.
                        if (!out.like_text) {
                            try {
                                const xrLike = document.evaluate(
                                    "/html/body/div[1]/div[2]/div[2]/div/div/div[1]/div[1]/div[2]/div[1]/h3/div[3]/strong",
                                    document,
                                    null,
                                    XPathResult.FIRST_ORDERED_NODE_TYPE,
                                    null
                                );
                                const nodeLike = xrLike.singleNodeValue;
                                if (nodeLike) out.like_text = (nodeLike.textContent || "").trim();
                            } catch (_) {}
                        }
                        if (!out.like_text) {
                            try {
                                const h3 = document.querySelector(
                                  "#main-content-others_homepage h3"
                                ) || document.querySelector("h3");
                                const txt = (h3?.innerText || "").replace(/\s+/g, " ").trim();
                                const m = txt.match(/([0-9.,]+(?:[KMB])?)\s*Likes?/i);
                                if (m) out.like_text = (m[1] || "").trim();
                            } catch (_) {}
                        }
                        if (!out.like_text) {
                            try {
                                const allText = (document.body?.innerText || "").replace(/\s+/g, " ");
                                const m2 = allText.match(/([0-9.,]+(?:[KMB])?)\s*Likes?/i);
                                if (m2) out.like_text = (m2[1] || "").trim();
                            } catch (_) {}
                        }
                        try {
                            const statBlocks = Array.from(document.querySelectorAll("h3 > div, [data-e2e='user-stats'] h3 > div"));
                            for (const block of statBlocks) {
                                const strong = block.querySelector("strong");
                                if (!strong) continue;
                                const value = (strong.textContent || "").trim();
                                if (!value) continue;
                                const labelText = (block.textContent || "").replace(value, "").trim().toLowerCase();
                                if (!out.follower_text && /(followers?|подписчики)/i.test(labelText)) {
                                    out.follower_text = value;
                                    continue;
                                }
                                if (!out.following_text && /(following|подписки)/i.test(labelText)) {
                                    out.following_text = value;
                                    continue;
                                }
                                if (!out.like_text && /(likes?|лайки|понрав)/i.test(labelText)) {
                                    out.like_text = value;
                                }
                            }
                        } catch (_) {}
                        const stats = Array.from(document.querySelectorAll("h3 strong"));
                        // Fallback order on TikTok profile header is usually:
                        // [0]=Following, [1]=Followers, [2]=Likes.
                        if (!out.following_text && stats[0]) out.following_text = (stats[0].textContent || "").trim();
                        if (!out.follower_text && stats[1]) out.follower_text = (stats[1].textContent || "").trim();
                        if (!out.like_text && stats[2]) out.like_text = (stats[2].textContent || "").trim();
                        if (!out.avatar_url) {
                            try {
                                const img =
                                  document.querySelector('[data-e2e="user-avatar"] img[src]') ||
                                  document.querySelector('span[data-e2e="user-avatar"] img[src]') ||
                                  document.querySelector('#main-content-others_homepage img[src]') ||
                                  document.querySelector('img[src*="tiktokcdn"]') ||
                                  document.querySelector('img[src*="muscdn"]');
                                const src = (img?.getAttribute("src") || "").trim();
                                if (src) out.avatar_url = src;
                            } catch (_) {}
                        }
                        return out;
                    }"""
                )
                print(f"[worker] profile_stats for @{profile_username}: {profile_stats}", file=sys.stderr)
            except Exception:
                profile_stats = {}

            if "login" in page.url or "passport" in page.url:
                if HEADLESS:
                    print(
                        "[worker] TikTok требует авторизации. "
                        "Запустите: python manage.py setup_tiktok_auth",
                        file=sys.stderr,
                    )
                    sys.exit(2)
                # Local dev: wait up to 2 min for manual login
                print("[worker] требуется вход — войдите в TikTok в открытом окне", file=sys.stderr)
                await page.wait_for_url("**/tiktok.com/**/", timeout=120_000)
                if profile_username and "/@" in (url or ""):
                    from platforms.tiktok.audience_scrape import _tiktok_goto_profile_with_redirect_recovery

                    await _tiktok_goto_profile_with_redirect_recovery(
                        page, profile_username, url.split("#")[0], _wu, rounds=4, dwell_s=9.0,
                    )
                else:
                    await page.goto(url, wait_until="domcontentloaded", timeout=30_000)

            # ── Error-page retry ─────────────────────────────────────────────
            # TikTok's SSR occasionally shows "Something went wrong" in a fresh
            # (cold-start) browser session. Сначала reload; если не помогло —
            # повторный goto на целевой URL профиля (без главной: у залогиненных
            # она часто открывает /foryou и мешает).
            for _err_retry in range(5):
                if items_captured:
                    break
                await asyncio.sleep(1.5)
                try:
                    is_error_page = await page.evaluate("""
                        () => {
                            const t = (document.body || {}).innerText || '';
                            return (
                                t.includes('Something went wrong') ||
                                t.includes('Что-то пошло не так') ||
                                t.includes('Ошибка на странице') ||
                                document.title === '' ||
                                (document.body && document.body.children.length <= 1 &&
                                 !document.querySelector('#app'))
                            );
                        }
                    """)
                except Exception:
                    is_error_page = False

                if is_error_page:
                    print(
                        f"[worker] error page on attempt {_err_retry + 1}, "
                        "trying page.reload() then повторный заход на целевой URL…",
                        file=sys.stderr,
                    )
                    try:
                        # Fast path: a hard reload sometimes resolves the transient
                        # "Something went wrong" screen without extra navigation.
                        try:
                            await page.reload(wait_until="domcontentloaded", timeout=20_000)
                            await asyncio.sleep(1.2)
                            still_error_after_reload = await page.evaluate("""
                                () => {
                                    const t = (document.body || {}).innerText || '';
                                    return (
                                        t.includes('Something went wrong') ||
                                        t.includes('Что-то пошло не так') ||
                                        t.includes('Ошибка на странице')
                                    );
                                }
                            """)
                        except Exception:
                            still_error_after_reload = True
                        if not still_error_after_reload:
                            print("[worker] page.reload() cleared error page", file=sys.stderr)
                            continue

                        # Без захода на главную: для залогиненных она часто = /foryou, ломает сценарий.
                        if profile_username and "/@" in (url or ""):
                            from platforms.tiktok.audience_scrape import _tiktok_goto_profile_with_redirect_recovery

                            await _tiktok_goto_profile_with_redirect_recovery(
                                page, profile_username, url.split("#")[0], _wu, rounds=6, dwell_s=9.0,
                            )
                        else:
                            await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
                        await asyncio.sleep(2)
                    except Exception as _nav_exc:
                        print(f"[worker] re-route failed: {_nav_exc}", file=sys.stderr)
                else:
                    break  # page looks normal — proceed to XHR wait

            # Явная страница "Couldn't find this account" на рендере браузера —
            # это надёжный признак, что профиль недоступен на площадке.
            if await _page_indicates_profile_unavailable(page):
                raise ValueError(
                    f"{PROFILE_UNAVAILABLE_MARK}TikTok @{profile_username or 'unknown'}: "
                    "профиль не найден или недоступен на площадке."
                )

            # Wait for videos to load — poll until we have items or timeout.
            # TikTok renders server-side HTML first, then fires the XHR.
            # Give it up to 30 seconds after domcontentloaded.
            print(f"[worker] waiting for item_list XHR on {url!r}…", file=sys.stderr)
            for _ in range(60):  # 60 × 0.5 s = 30 s
                if items_captured:
                    break
                await asyncio.sleep(0.5)

            if not items_captured:
                print(
                    f"[worker] no items after 30 s, trying scroll "
                    f"(matched urls: {all_item_urls})",
                    file=sys.stderr,
                )
                # Scroll and wait another 10 seconds
                try:
                    for _ in range(3):
                        await page.evaluate("window.scrollBy(0, 600)")
                        await asyncio.sleep(1)
                        if items_captured:
                            break
                    if not items_captured:
                        await asyncio.sleep(7)
                except Exception:
                    pass

            # ── DOM / script fallback ────────────────────────────────────────
            # Three strategies tried in order:
            #  1. Parse __UNIVERSAL_DATA_FOR_REHYDRATION__ from the browser-rendered page
            #     (browser may send cookies that cause TikTok to include video data in SSR)
            #  2. [data-e2e="user-post-item"] cards (only present when XHR already fired)
            #  3. Any a[href*="/video/"] links on the page
            if not items_captured:
                print("[worker] XHR empty — attempting DOM/script extraction…", file=sys.stderr)
                try:
                    page_title = await page.title()
                    print(f"[worker] page: title={page_title!r} url={page.url!r}", file=sys.stderr)

                    # Wait briefly for something meaningful to render
                    try:
                        await page.wait_for_selector(
                            '[data-e2e="user-post-item"], '
                            'script#__UNIVERSAL_DATA_FOR_REHYDRATION__',
                            timeout=10_000,
                        )
                    except Exception:
                        pass

                    dom_result = await page.evaluate(r"""
                        () => {
                            const out = { items: [], source: 'none', debug: {} };

                            // ── Strategy 1: __UNIVERSAL_DATA_FOR_REHYDRATION__ ──────
                            const scriptEl = document.getElementById(
                                '__UNIVERSAL_DATA_FOR_REHYDRATION__'
                            );
                            if (scriptEl) {
                                try {
                                    const data = JSON.parse(scriptEl.textContent);
                                    const scope = (data || {}).__DEFAULT_SCOPE__ || {};
                                    out.debug.scopeKeys = Object.keys(scope);

                                    for (const k of Object.keys(scope)) {
                                        const v = scope[k];
                                        if (!v || typeof v !== 'object') continue;

                                        // Check known list-field names
                                        for (const lk of ['itemList', 'videoList', 'items']) {
                                            if (Array.isArray(v[lk]) && v[lk].length > 0) {
                                                out.items = v[lk];
                                                out.source = 'universal:' + k + '.' + lk;
                                                return out;
                                            }
                                        }
                                        // Generic: any subkey that is a non-empty array
                                        // whose first element has an id/aweme_id field
                                        for (const sk of Object.keys(v)) {
                                            const sv = v[sk];
                                            if (
                                                Array.isArray(sv) && sv.length > 0 &&
                                                sv[0] && typeof sv[0] === 'object' &&
                                                ('id' in sv[0] || 'aweme_id' in sv[0])
                                            ) {
                                                // Normalise aweme_id → id
                                                out.items = sv.map(function(item) {
                                                    if (!item.id && item.aweme_id) {
                                                        return Object.assign({}, item, { id: item.aweme_id });
                                                    }
                                                    return item;
                                                });
                                                out.source = 'universal:' + k + '.' + sk;
                                                return out;
                                            }
                                        }
                                    }
                                } catch (e) {
                                    out.debug.scriptError = String(e);
                                }
                            } else {
                                out.debug.noUniversalScript = true;
                            }

                            // ── Helpers for strategies 2 & 3 ────────────────────────
                            function parseCount(text) {
                                if (!text) return 0;
                                text = text.trim().replace(/,/g, '');
                                const m = text.match(/^([\d.]+)([KMkm]?)$/);
                                if (!m) return 0;
                                const n = parseFloat(m[1]);
                                const s = m[2].toUpperCase();
                                return s === 'K' ? Math.round(n * 1000)
                                     : s === 'M' ? Math.round(n * 1000000)
                                     : Math.round(n);
                            }

                            function itemFromContainer(el) {
                                const link = el.querySelector('a[href*="/video/"]');
                                if (!link) return null;
                                const href = link.getAttribute('href') || link.href || '';
                                const m = href.match(/\/video\/(\d+)/);
                                if (!m) return null;
                                const img = el.querySelector('img');
                                const cover = img
                                    ? (img.getAttribute('data-src') || img.getAttribute('src') || img.src || '')
                                    : '';
                                const desc = img ? (img.getAttribute('alt') || '') : '';
                                let viewCount = 0;
                                for (const s of el.querySelectorAll('strong')) {
                                    const t = s.textContent.trim();
                                    if (/^[\d.,]+[KMkm]?$/.test(t)) {
                                        viewCount = parseCount(t);
                                        break;
                                    }
                                }
                                return {
                                    id: m[1], desc: desc,
                                    video: { cover: cover },
                                    stats: { playCount: viewCount, diggCount: 0, commentCount: 0, shareCount: 0 },
                                    createTime: 0
                                };
                            }

                            // ── Strategy 2: [data-e2e="user-post-item"] ──────────────
                            const e2eItems = document.querySelectorAll('[data-e2e="user-post-item"]');
                            out.debug.e2eCount = e2eItems.length;
                            for (const el of e2eItems) {
                                const item = itemFromContainer(el);
                                if (item) out.items.push(item);
                            }
                            if (out.items.length > 0) {
                                out.source = 'dom:e2e';
                                return out;
                            }

                            // ── Strategy 3: any a[href*="/video/"] on the page ───────
                            const seen = new Set();
                            const allLinks = document.querySelectorAll('a[href*="/video/"]');
                            out.debug.videoLinkCount = allLinks.length;
                            for (const link of allLinks) {
                                const href = link.getAttribute('href') || link.href || '';
                                const m = href.match(/\/video\/(\d+)/);
                                if (!m || seen.has(m[1])) continue;
                                seen.add(m[1]);
                                const container =
                                    link.closest('li') ||
                                    link.closest('article') ||
                                    link.parentElement;
                                const item = itemFromContainer(container || link);
                                if (item) out.items.push(item);
                            }
                            if (out.items.length > 0) out.source = 'dom:links';
                            return out;
                        }
                    """)

                    debug_info = dom_result.get("debug", {})
                    source = dom_result.get("source", "none")
                    found_items = dom_result.get("items", [])
                    print(
                        f"[worker] fallback source={source!r} "
                        f"items={len(found_items)} debug={debug_info}",
                        file=sys.stderr,
                    )

                    if found_items:
                        items_captured.extend(found_items)

                    # ── Strategy 4: in-page fetch() to item_list API ─────────
                    # Uses the browser's own credentials + headers so TikTok
                    # sees a same-origin request with all the right cookies/tokens.
                    if not items_captured:
                        print("[worker] trying in-page fetch() to item_list API…", file=sys.stderr)
                        try:
                            api_result = await page.evaluate(r"""
                                async () => {
                                    // Extract secUid from SSR data
                                    let secUid = '';
                                    const scriptEl = document.getElementById('__UNIVERSAL_DATA_FOR_REHYDRATION__');
                                    if (scriptEl) {
                                        try {
                                            const d = JSON.parse(scriptEl.textContent);
                                            const sc = (d || {}).__DEFAULT_SCOPE__ || {};
                                            const ud = sc['webapp.user-detail'];
                                            secUid = ud?.userInfo?.user?.secUid || '';
                                        } catch (_) {}
                                    }
                                    if (!secUid) return { error: 'no secUid on page' };

                                    const params = new URLSearchParams({
                                        aid: '1988',
                                        app_name: 'tiktok_web',
                                        device_platform: 'web_pc',
                                        os: 'windows',
                                        secUid: secUid,
                                        count: '35',
                                        cursor: '0',
                                        coverFormat: '2',
                                        version_name: '32.5.0',
                                        language: 'en',
                                    });
                                    const apiUrl = '/api/post/item_list/?' + params.toString();
                                    try {
                                        const resp = await fetch(apiUrl, {
                                            method: 'GET',
                                            credentials: 'include',
                                            headers: {
                                                'Accept': 'application/json, text/plain, */*',
                                                'Referer': window.location.href,
                                            }
                                        });
                                        const text = await resp.text();
                                        return { status: resp.status, text: text.slice(0, 8000) };
                                    } catch (e) {
                                        return { error: String(e) };
                                    }
                                }
                            """)
                            print(f"[worker] in-page fetch result: status={api_result.get('status')!r} err={api_result.get('error')!r}", file=sys.stderr)
                            if api_result.get("status") == 200 and api_result.get("text"):
                                try:
                                    api_json = json.loads(api_result["text"])
                                    api_items = api_json.get("itemList") or []
                                    print(f"[worker] in-page fetch items={len(api_items)}", file=sys.stderr)
                                    if api_items:
                                        items_captured.extend(api_items)
                                except Exception as _parse_exc:
                                    print(f"[worker] in-page fetch parse error: {_parse_exc}", file=sys.stderr)
                        except Exception as _fetch_exc:
                            print(f"[worker] in-page fetch error: {_fetch_exc}", file=sys.stderr)

                    if not items_captured:
                        print("[worker] all fallback strategies failed — no posts found", file=sys.stderr)

                except Exception as exc:
                    print(f"[worker] DOM extraction error: {exc}", file=sys.stderr)
                    if "closed" in str(exc).lower():
                        raise

            # TikTok подгружает следующие страницы item_list только при скролле.
            if items_captured:
                u0 = _uniq_items_count(items_captured)
                print(
                    f"[worker] expanding feed by scroll: unique={u0}, "
                    f"target_post_count={target_post_count or '—'}",
                    file=sys.stderr,
                )
                stable = 0
                prev_u = u0
                chasing_target = bool(target_post_count and prev_u < target_post_count)
                max_rounds = 100 if chasing_target else 26
                stable_limit = 14 if chasing_target else 8
                for _rnd in range(max_rounds):
                    u = _uniq_items_count(items_captured)
                    if target_post_count and u >= target_post_count:
                        break
                    await page.evaluate(
                        "window.scrollBy(0, Math.floor(window.innerHeight * 0.92))"
                    )
                    await asyncio.sleep(1.15 if chasing_target else 1.05)
                    u2 = _uniq_items_count(items_captured)
                    if u2 == prev_u:
                        stable += 1
                        if stable >= stable_limit:
                            break
                    else:
                        stable = 0
                    prev_u = u2
                print(
                    f"[worker] after scroll: unique={_uniq_items_count(items_captured)}",
                    file=sys.stderr,
                )

            deduped_items = _dedupe_item_list(items_captured)
            items_captured.clear()
            items_captured.extend(deduped_items)

            if items_captured:
                if profile_username:
                    matched_by_author = 0
                    kept_without_author = 0
                    for it in items_captured:
                        author = it.get("author", {}) if isinstance(it, dict) else {}
                        a_user = str(author.get("uniqueId") or "").strip().lower()
                        if a_user == profile_username:
                            collected.append(it)
                            matched_by_author += 1
                            continue
                        # Some TikTok API variants omit author for profile item_list.
                        # In that case keep the item to avoid dropping the whole feed.
                        if not a_user:
                            collected.append(it)
                            kept_without_author += 1
                    print(
                        f"[worker] collected={len(collected)} "
                        f"(author_match={matched_by_author}, no_author={kept_without_author})",
                        file=sys.stderr,
                    )
                else:
                    collected.extend(items_captured)

            # Refresh saved cookies after a successful run
            if state_path:
                await context.storage_state(path=str(state_path))

    except Exception as e:
        if str(e).startswith(PROFILE_UNAVAILABLE_MARK):
            raise
        print(f"[worker] error: {e}", file=sys.stderr)
    finally:
        if own_page:
            try:
                await page.close()
            except Exception:
                pass
    return {
        "items": collected,
        "profile_stats": profile_stats,
    }


def _load_worker_utils():
    _utils_path = Path(__file__).parent.parent / "worker_utils.py"
    if not _utils_path.exists():
        print(
            f"[tiktok_worker] ERROR: worker_utils.py not found at {_utils_path}",
            file=sys.stderr,
        )
        return None
    import importlib.util as _ilu
    _spec = _ilu.spec_from_file_location("worker_utils", _utils_path)
    _wu = _ilu.module_from_spec(_spec)
    _spec.loader.exec_module(_wu)
    return _wu


async def _create_tiktok_context(pw, _wu):
    # Incognito mode: always launch a regular browser + ephemeral context.
    # If state file exists, load cookies/session into this context.
    profile_base = Path(PROFILE_DIR)
    if _wu is not None:
        state_path = _wu.state_file_path("tiktok", profile_base)
    else:
        state_path = Path(STATE_FILE) if STATE_FILE else profile_base / "tiktok_state.json"

    # headless читается из BROWSER_HEADLESS / TIKTOK_HEADLESS (см. resolve_headless).
    if _wu is not None and hasattr(_wu, "resolve_headless"):
        headless = _wu.resolve_headless(platform="tiktok")
    else:
        headless = (os.environ.get("BROWSER_HEADLESS", "false").strip().lower()
                    in {"1", "true", "yes", "on", "y"})

    # channel="chrome" требует системный Google Chrome — на сервере без него.
    # На Windows/macOS (локалка) по умолчанию используем системный Chrome — это
    # историческое поведение и оно лучше проходит детект TikTok. На Linux/сервере
    # дефолт — встроенный Chromium Playwright. Переопределить через
    # TIKTOK_BROWSER_CHANNEL=chrome|chromium|""(пусто = bundled).
    _default_channel = "chrome" if sys.platform != "linux" else ""
    channel = os.environ.get("TIKTOK_BROWSER_CHANNEL", _default_channel).strip()
    launch_kwargs = {
        "headless": headless,
        "args": ["--disable-blink-features=AutomationControlled"],
    }
    if channel:
        launch_kwargs["channel"] = channel
    browser = await pw.chromium.launch(**launch_kwargs)
    if state_path.exists():
        context = await browser.new_context(
            storage_state=str(state_path),
            locale="en-US",
            viewport={"width": 1280, "height": 900},
        )
    else:
        context = await browser.new_context(
            locale="en-US",
            viewport={"width": 1280, "height": 900},
        )
    return context, browser, state_path


async def run_once(data: dict) -> None:
    from playwright.async_api import async_playwright
    from platforms.worker_utils import finish_cli_session_keep_browser_by_default

    _wu = _load_worker_utils()

    async with async_playwright() as pw:
        context, _browser, state_path = await _create_tiktok_context(pw, _wu)
        try:
            out = await _run_with_context(data, context, _wu, state_path)
        except (KeyboardInterrupt, SystemExit):
            raise
        except BaseException as exc:
            _write_response({"error": f"Ошибка worker: {exc}"})
            await finish_cli_session_keep_browser_by_default("tiktok_worker", context, _browser)
            return
        _write_response(out)
        await finish_cli_session_keep_browser_by_default("tiktok_worker", context, _browser)


def _write_response(payload) -> None:
    # Windows console can be cp1251; keep JSON ASCII-safe to avoid daemon crash
    # on emoji/non-cp1251 characters from TikTok captions.
    print(json.dumps(payload, ensure_ascii=True), flush=True)


def _run_daemon() -> None:
    async def daemon_main():
        from playwright.async_api import async_playwright
        from platforms.worker_utils import (
            daemon_idle_keep_browser_open,
            worker_autoclose_browser_on_daemon_exit,
        )

        _wu = _load_worker_utils()
        async with async_playwright() as pw:
            context, _browser, state_path = await _create_tiktok_context(pw, _wu)
            try:
                page = context.pages[0] if context.pages else await context.new_page()
                await _wu.warm_playwright_page_home(page, "tiktok")
                for line in sys.stdin:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        payload = json.loads(line)
                    except Exception:
                        _write_response({"error": "Невалидный JSON payload"})
                        continue
                    try:
                        if page.is_closed():
                            result = {"error": "Вкладка TikTok закрыта. Откройте окно и повторите обновление."}
                            _write_response(result)
                            continue
                        result = await _run_with_context(payload, context, _wu, state_path, page=page)
                    except Exception as exc:
                        result = {"error": f"Ошибка worker: {exc}"}
                    _write_response(result)
            finally:
                if worker_autoclose_browser_on_daemon_exit():
                    await context.close()
                    if _browser is not None:
                        try:
                            await _browser.close()
                        except Exception:
                            pass
                else:
                    await daemon_idle_keep_browser_open("tiktok_worker", page, platform="tiktok")

    asyncio.run(daemon_main())


if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "--daemon":
        _run_daemon()
    else:
        if len(sys.argv) < 2:
            _write_response({"error": "Отсутствует payload"})
            sys.exit(1)
        try:
            one_payload = json.loads(sys.argv[1])
        except Exception:
            _write_response({"error": "Невалидный JSON payload"})
            sys.exit(1)
        asyncio.run(run_once(one_payload))
