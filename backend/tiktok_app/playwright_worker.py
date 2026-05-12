"""
Playwright subprocess worker for TikTok video list.

Server mode  (BROWSER_HEADLESS=true):
  Uses a storage_state JSON file (BROWSER_STATE_FILE) with exported cookies.
  Run `python manage.py setup_tiktok_auth` once to log in and export the file.

Local dev mode (BROWSER_HEADLESS=false or not set):
  Uses a persistent Chromium profile at BROWSER_PROFILE_DIR
  (auto-detected cross-platform default if not set).
  Shows browser window so you can log in manually once.
"""
import asyncio
import json
import os
import re
import sys
from pathlib import Path


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


async def main() -> None:
    data = json.loads(sys.argv[1])
    url: str = data["url"]

    from playwright.async_api import async_playwright

    collected: list[dict] = []

    async with async_playwright() as pw:
        # Import helper — resolve path relative to this file so it works both
        # when invoked as a subprocess and when imported directly.
        _utils_path = Path(__file__).parent.parent / "accounts" / "worker_utils.py"
        if _utils_path.exists():
            import importlib.util as _ilu
            _spec = _ilu.spec_from_file_location("worker_utils", _utils_path)
            _wu = _ilu.module_from_spec(_spec)
            _spec.loader.exec_module(_wu)
        else:
            _wu = None

        # headless определяется через BROWSER_HEADLESS / TIKTOK_HEADLESS.
        if _wu is not None and hasattr(_wu, "resolve_headless"):
            _headless = _wu.resolve_headless(platform="tiktok")
        else:
            _headless = (os.environ.get("BROWSER_HEADLESS", "false").strip().lower()
                         in {"1", "true", "yes", "on", "y"})

        if _wu is not None:
            context, _browser = await _wu.launch_context(
                pw,
                platform="tiktok",
                profile_dir=Path(PROFILE_DIR),
                locale="en-US",
            )
            owns_browser = _browser is not None
            _owned_browser = _browser
            state_path = _wu.state_file_path("tiktok", Path(PROFILE_DIR))
        else:
            # Fallback if worker_utils not found (standalone deployment)
            state_path = Path(STATE_FILE) if STATE_FILE else Path(PROFILE_DIR) / "tiktok_state.json"
            if state_path.exists():
                browser = await pw.chromium.launch(headless=_headless)
                context = await browser.new_context(
                    storage_state=str(state_path),
                    locale="en-US",
                    viewport={"width": 1280, "height": 900},
                )
                owns_browser = True
                _owned_browser = browser
            else:
                Path(PROFILE_DIR).mkdir(parents=True, exist_ok=True)
                context = await pw.chromium.launch_persistent_context(
                    PROFILE_DIR, headless=_headless,
                    args=["--disable-blink-features=AutomationControlled"],
                    locale="en-US", viewport={"width": 1280, "height": 900},
                )
                owns_browser = False
                _owned_browser = None

        try:
            # Always open a fresh page to ensure a clean load and a fresh
            # api/post/item_list request (reusing an existing TikTok SPA
            # page may skip the XHR if TikTok handles navigation client-side).
            page = await context.new_page()

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

            m_prof = re.search(r"/@([^/?#]+)", url or "")
            prof_handle = (m_prof.group(1).strip().lower() if m_prof else "")
            is_profile_job = bool(prof_handle) and "/@" in (url or "")

            # Прогрев через главную для залогиненных даёт /for_you — потом профиль
            # не открывается стабильно. Для URL с /@… сразу идём на профиль.
            if not is_profile_job:
                try:
                    await page.goto("https://www.tiktok.com/", wait_until="domcontentloaded", timeout=20_000)
                    await asyncio.sleep(1.5)
                except Exception as _warm_exc:
                    print(f"[worker] homepage warm-up failed (non-fatal): {_warm_exc}", file=sys.stderr)

            if is_profile_job:
                from platforms.tiktok.audience_scrape import _tiktok_goto_profile_with_redirect_recovery

                await _tiktok_goto_profile_with_redirect_recovery(
                    page, prof_handle, url.split("#")[0], _wu, rounds=5, dwell_s=11.0,
                )
            else:
                await page.goto(url, wait_until="domcontentloaded", timeout=30_000)

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
                if is_profile_job:
                    from platforms.tiktok.audience_scrape import _tiktok_goto_profile_with_redirect_recovery

                    await _tiktok_goto_profile_with_redirect_recovery(
                        page, prof_handle, url.split("#")[0], _wu, rounds=5, dwell_s=11.0,
                    )
                else:
                    await page.goto(url, wait_until="domcontentloaded", timeout=30_000)

            # ── Error-page retry ─────────────────────────────────────────────
            # TikTok's SSR occasionally fails and shows "Something went wrong /
            # Что-то пошло не так" with a Refresh button.  The React app never
            # mounts so no XHR fires.  Click the on-page Refresh button (same as
            # a real user would do) up to 5 times until the page loads cleanly.
            for _err_retry in range(5):
                if items_captured:
                    break
                await asyncio.sleep(1)
                try:
                    is_error_page = await page.evaluate("""
                        () => {
                            const t = (document.body || {}).innerText || '';
                            return (
                                t.includes('Something went wrong') ||
                                t.includes('Что-то пошло не так') ||
                                t.includes('Ошибка на странице') ||
                                document.title === '' ||
                                // Empty body — React hasn't mounted
                                (document.body && document.body.children.length <= 1 &&
                                 !document.querySelector('#app'))
                            );
                        }
                    """)
                except Exception:
                    is_error_page = False

                if is_error_page:
                    print(
                        f"[worker] TikTok error page detected (attempt {_err_retry + 1}), "
                        "clicking refresh button…",
                        file=sys.stderr,
                    )
                    try:
                        # Try clicking the on-page "Refresh" / "Обновить" button first —
                        # identical to what a user does when they see the error page.
                        clicked = await page.evaluate("""
                            () => {
                                const keywords = ['refresh', 'обновить', 'try again',
                                                  'попробуй', 'reload', 'повторить'];
                                const btns = [
                                    ...document.querySelectorAll('button'),
                                    ...document.querySelectorAll('[role="button"]'),
                                    ...document.querySelectorAll('a'),
                                ];
                                for (const btn of btns) {
                                    const t = (btn.textContent || btn.innerText || '').toLowerCase();
                                    if (keywords.some(k => t.includes(k))) {
                                        btn.click();
                                        return true;
                                    }
                                }
                                return false;
                            }
                        """)
                        if clicked:
                            print("[worker] refresh button clicked", file=sys.stderr)
                            await asyncio.sleep(3)
                        else:
                            # No button found — fall back to programmatic reload
                            print("[worker] no refresh button, using page.reload()", file=sys.stderr)
                            await page.reload(wait_until="domcontentloaded", timeout=30_000)
                            await asyncio.sleep(2)
                    except Exception as _rel_exc:
                        print(f"[worker] reload failed: {_rel_exc}", file=sys.stderr)
                else:
                    break  # page looks normal

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

            if items_captured:
                collected.extend(items_captured)

            # Refresh saved cookies after a successful run
            if state_path:
                await context.storage_state(path=str(state_path))

        except Exception as e:
            print(f"[worker] error: {e}", file=sys.stderr)
        finally:
            await context.close()
            if owns_browser and _owned_browser is not None:
                await _owned_browser.close()

    print(json.dumps(collected))


asyncio.run(main())
