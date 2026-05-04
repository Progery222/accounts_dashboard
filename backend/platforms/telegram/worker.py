"""
Standalone subprocess — fetches Telegram channel data via web.telegram.org/k/.
Invoked by platforms/telegram/scraper.py as:
    python telegram/worker.py '{"username": "channelname"}'

IMPORTANT: Telegram Web stores the auth key in IndexedDB, which is NOT captured
by Playwright's storage_state JSON. Therefore this worker ALWAYS uses the
persistent Chrome profile (force_persistent=True) so that IndexedDB is preserved
across runs. The user only needs to log in once via Settings → «Войти в Telegram».

Runs headless=True — no browser window appears. If the session is expired the
worker detects the QR/auth page within a few seconds and exits with an error,
so the QR code window never shows up.
"""
import asyncio
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from playwright.async_api import async_playwright

NAV_TIMEOUT  = 30_000   # ms
LOAD_TIMEOUT = 20_000   # ms
AUTH_DETECT_TIMEOUT = 10_000  # ms — fail fast if QR page detected


# ── Parse helpers ─────────────────────────────────────────────────────────────

def _parse_count(text: str) -> int:
    """'1 234 подписчиков' / '88.4K' / '1.2M members' → int."""
    if not text:
        return 0
    text = re.split(
        r'[\s\u00a0\u202f]+(?:subscriber|member|follower|подписч|участн)',
        text, flags=re.I,
    )[0]
    text = (text.replace('\xa0', '').replace('\u202f', '')
               .replace(' ', '').replace(',', '.'))
    m = re.match(r'^([\d]+(?:\.[\d]+)?)\s*([KMBTkmbt]?)$', text)
    if m:
        try:
            num  = float(m.group(1))
            mult = {'K': 1_000, 'M': 1_000_000, 'B': 1_000_000_000,
                    'T': 1_000_000_000_000}.get(m.group(2).upper(), 1)
            return int(num * mult)
        except ValueError:
            pass
    digits = re.sub(r'[^\d]', '', text)
    return int(digits) if digits else 0


def _parse_views(text: str) -> int:
    """'1.2K' / '88 400' → int."""
    if not text:
        return 0
    text = (text.strip()
               .replace('\xa0', '').replace('\u202f', '')
               .replace(' ', '').replace(',', '.'))
    m = re.match(r'^([\d]+(?:\.[\d]+)?)\s*([KMBkmb]?)$', text)
    if not m:
        return 0
    num    = float(m.group(1))
    suffix = m.group(2).upper()
    return int(num * {'K': 1_000, 'M': 1_000_000, 'B': 1_000_000_000}.get(suffix, 1))


# ── Auth detection JS ─────────────────────────────────────────────────────────

# Returns "auth"      → QR / login page is visible   → fail fast
# Returns "loaded"    → main chat UI is ready         → continue
# Returns "loading"   → still initialising            → keep waiting
_STATE_JS = """
    () => {
        // Auth overlay clearly visible
        const auth = document.querySelector('#auth-pages, .auth-page, .page-sign');
        if (auth) {
            const st = window.getComputedStyle(auth);
            if (st.display !== 'none' && st.visibility !== 'hidden') return 'auth';
        }
        // Body flag: session check still in progress
        if (document.body && document.body.classList.contains('has-auth-pages')) return 'loading';
        // Chat UI elements
        if (
            document.querySelector('#column-left')        ||
            document.querySelector('.sidebar-left')       ||
            document.querySelector('.chat-list')          ||
            document.querySelector('.chatlist')           ||
            document.querySelector('.dialogs-container')  ||
            document.querySelector('[class*="chatList"]') ||
            document.querySelector('.LeftColumn')         ||
            document.querySelector('.chat-info')
        ) return 'loaded';
        return 'loading';
    }
"""


# ── Main ──────────────────────────────────────────────────────────────────────

def _load_worker_utils():
    import importlib.util as _ilu
    _wu_path = Path(__file__).parent.parent / "worker_utils.py"
    if not _wu_path.exists():
        raise RuntimeError(f"worker_utils.py not found at {_wu_path}")
    _wu_spec = _ilu.spec_from_file_location("worker_utils", _wu_path)
    _wu = _ilu.module_from_spec(_wu_spec)
    _wu_spec.loader.exec_module(_wu)
    return _wu


async def _run_with_page(username: str, page, _wu):
    if True:

        # ── 1. Navigate ───────────────────────────────────────────────────────
        print(f"[telegram_worker] navigating to @{username}", file=sys.stderr)
        await page.goto(
            f"https://web.telegram.org/k/#@{username}",
            wait_until="domcontentloaded",
            timeout=NAV_TIMEOUT,
        )
        await _wu.wait_for_anti_bot_clear(page, platform="telegram")

        # ── 2. Wait for state to resolve (auth OR chat UI) ────────────────────
        # The function returns a non-"loading" value as soon as auth is confirmed
        # or the chat UI appears. This way we fail fast on QR code instead of
        # waiting the full 30 seconds.
        print("[telegram_worker] waiting for session state…", file=sys.stderr)
        try:
            await page.wait_for_function(
                f"() => {{ const s = ({_STATE_JS})(); return s !== 'loading'; }}",
                timeout=AUTH_DETECT_TIMEOUT,
            )
        except Exception:
            # Timed out — neither auth nor chat UI appeared.
            # Fall through; the state check below will surface an error.
            pass

        state = await page.evaluate(_STATE_JS)
        print(f"[telegram_worker] session state: {state!r}", file=sys.stderr)

        if state != "loaded":
            return {
                "error": (
                    "Telegram требует авторизации — нажмите «Войти в Telegram» "
                    "в настройках приложения."
                )
            }

        # ── 3. Wait for channel header ────────────────────────────────────────
        try:
            await page.wait_for_selector(
                "#column-center .peer-title, .chat-info .peer-title",
                timeout=LOAD_TIMEOUT,
            )
        except Exception:
            return {"error": f"Telegram @{username} не найден или не загрузился."}

        # Wait for messages + reactions to render.
        # Reactions in Telegram Web K load asynchronously after the main messages.
        await page.wait_for_timeout(4000)

        # ── 4. Channel header info ────────────────────────────────────────────
        info = await page.evaluate("""
            () => {
                const nameEl =
                    document.querySelector('#column-center .peer-title') ||
                    document.querySelector('.chat-info .peer-title');
                const subEl =
                    document.querySelector('#column-center .peer-status') ||
                    document.querySelector('.chat-info .peer-status') ||
                    document.querySelector('.chat-info .info span');
                return {
                    name:        nameEl ? nameEl.textContent.trim() : '',
                    subscribers: subEl  ? subEl.textContent.trim()  : '',
                };
            }
        """)

        display_name   = info.get("name", "").strip() or username
        follower_count = _parse_count(info.get("subscribers", ""))
        print(f"[telegram_worker] @{username}: {display_name!r}, {follower_count} subscribers",
              file=sys.stderr)

        # ── 5. Debug: dump reaction-related class names from first bubble ────────
        try:
            reaction_debug = await page.evaluate("""
                () => {
                    const bubbles = document.querySelectorAll(
                        '.bubbles-inner .bubble:not(.is-service),' +
                        '.chat-bubbles .bubble:not(.is-service),'  +
                        '#column-center .bubble:not(.is-service)'
                    );
                    const info = [];
                    for (const b of Array.from(bubbles).slice(0, 5)) {
                        const els = b.querySelectorAll('*');
                        const classes = new Set();
                        for (const el of els) {
                            for (const cls of el.classList) {
                                if (/react|count|like/i.test(cls)) classes.add(cls);
                            }
                        }
                        if (classes.size > 0) {
                            info.push(Array.from(classes).join(' '));
                        }
                    }
                    return info;
                }
            """)
            print(f"[telegram_worker] reaction classes found: {reaction_debug}", file=sys.stderr)
        except Exception:
            pass

        # ── 6. Extract messages ───────────────────────────────────────────────
        posts_raw = await page.evaluate("""
            () => {
                // Helper: parse "1.2K" / "88 400" / "42" → integer
                function parseNum(t) {
                    t = (t || '').trim()
                        .replace(/[\\s\\u00a0\\u202f]/g, '')
                        .replace(',', '.');
                    const m = t.match(/^([\\d]+(?:\\.[\\d]+)?)([KkMm]?)$/);
                    if (!m) return 0;
                    const n    = parseFloat(m[1]);
                    const mult = { K: 1000, M: 1000000 }[m[2].toUpperCase()] || 1;
                    return Math.round(n * mult);
                }

                // Helper: find the first numeric leaf-text element inside a container.
                // "Leaf" means no child elements — avoids double-counting wrappers.
                function firstNumericLeaf(container) {
                    if (!container) return 0;
                    for (const el of container.querySelectorAll('*')) {
                        if (el.children.length > 0) continue;  // skip wrappers
                        const t = (el.textContent || '').trim()
                            .replace(/[\\s\\u00a0\\u202f]/g, '')
                            .replace(',', '.');
                        if (/^[\\d]+(?:\\.[\\d]+)?[KkMm]?$/.test(t)) return parseNum(t);
                    }
                    return 0;
                }

                const results = [];
                const bubbles = document.querySelectorAll(
                    '.bubbles-inner .bubble:not(.is-service),'  +
                    '.chat-bubbles .bubble:not(.is-service),'   +
                    '#column-center .bubble:not(.is-service)'
                );

                for (const bubble of bubbles) {
                    try {
                        const mid = (bubble.dataset.mid || '').trim();
                        if (!mid) continue;

                        // ── Text ──────────────────────────────────────────────
                        const msgEl = bubble.querySelector('.message') ||
                                      bubble.querySelector('.translatable-message');
                        const text = msgEl ? msgEl.innerText.trim().slice(0, 500) : '';

                        // ── Views ─────────────────────────────────────────────
                        let viewsText = '';
                        const viewsEl =
                            bubble.querySelector('.message-views-counter')   ||
                            bubble.querySelector('.post-views .views-count') ||
                            bubble.querySelector('.post-views span')         ||
                            bubble.querySelector('.views-count')             ||
                            bubble.querySelector('.channel-post-views');
                        if (viewsEl) {
                            viewsText = (viewsEl.innerText || viewsEl.textContent || '').trim();
                        }
                        if (!viewsText) {
                            const pvEl = bubble.querySelector('.post-views');
                            if (pvEl) {
                                const chunks = [];
                                for (const n of pvEl.childNodes) {
                                    if (n.nodeType === 3) {
                                        const t = n.textContent.trim();
                                        if (t) chunks.push(t);
                                    }
                                }
                                viewsText = chunks.join('') ||
                                    pvEl.textContent.replace(/[^\\d.,KkMmBb]/g, '');
                            }
                        }

                        // ── First reaction (most popular) ─────────────────────
                        // Strategy 1: find the reactions container, then the first
                        //             numeric leaf element inside it.
                        let topReaction = 0;
                        const reactContainer =
                            bubble.querySelector('.reactions')          ||
                            bubble.querySelector('.reactions-bubble')   ||
                            bubble.querySelector('[class*="reactions"]');
                        if (reactContainer) {
                            topReaction = firstNumericLeaf(reactContainer);
                        }

                        // Strategy 2: any element whose class mentions "reaction"
                        //             and whose text is just a number.
                        if (topReaction === 0) {
                            for (const el of bubble.querySelectorAll('[class*="reaction"]')) {
                                if (el.children.length > 0) continue;
                                const v = parseNum(el.textContent);
                                if (v > 0) { topReaction = v; break; }
                            }
                        }

                        // Strategy 3: aria-label contains "reaction" count
                        if (topReaction === 0) {
                            for (const el of bubble.querySelectorAll('[aria-label]')) {
                                const lbl = el.getAttribute('aria-label') || '';
                                const m = lbl.match(/(\\d[\\d\\s,.]*)\\s*react/i);
                                if (m) {
                                    topReaction = parseInt(m[1].replace(/[^\\d]/g, ''), 10) || 0;
                                    if (topReaction > 0) break;
                                }
                            }
                        }

                        // ── Timestamp ─────────────────────────────────────────
                        const timeEl = bubble.querySelector('.time-inner');
                        const ts = timeEl ? (timeEl.dataset.timestamp || '') : '';

                        // ── Thumbnail (skip blob: URLs) ───────────────────────
                        let thumb = '';
                        const imgEl = bubble.querySelector('.media-photo img') ||
                                      bubble.querySelector('.media-sticker img');
                        if (imgEl && imgEl.src && !imgEl.src.startsWith('blob:')) {
                            thumb = imgEl.src;
                        }

                        results.push({ mid, text, views: viewsText,
                                       reactions: topReaction, ts, thumb });
                    } catch (e) { /* skip malformed bubble */ }
                }
                return results;
            }
        """)

    # ── 6. Post-process ───────────────────────────────────────────────────────
    posts = []
    real_ids: list[int] = []

    for p in posts_raw:
        mid = str(p.get("mid", "")).strip()
        if not mid:
            continue

        ts = p.get("ts", "")
        posted_at = None
        if ts:
            try:
                posted_at = datetime.fromtimestamp(int(ts), tz=timezone.utc).isoformat()
            except Exception:
                pass

        # data-mid can be an encoded value; use it as-is for dedup.
        # For the public t.me link use the lower 20 bits as the server-side msg ID.
        try:
            mid_int  = int(mid)
            real_id  = mid_int & 0xFFFFF if mid_int > 0xFFFFF else mid_int
            if real_id > 0:
                real_ids.append(real_id)
            post_url = f"https://t.me/{username}/{real_id}" if real_id > 0 else ""
        except ValueError:
            post_url = ""

        posts.append({
            "external_id":   mid,
            "description":   p.get("text", ""),
            "thumbnail_url": p.get("thumb", ""),
            "post_url":      post_url,
            "view_count":    _parse_views(p.get("views", "")),
            "like_count":    p.get("reactions", 0),
            "comment_count": 0,
            "share_count":   0,
            "posted_at":     posted_at,
        })

    print(f"[telegram_worker] extracted {len(posts)} messages", file=sys.stderr)

    post_count_estimate = max(real_ids) if real_ids else (len(posts) if posts else None)

    return {
        "display_name":   display_name,
        "avatar_url":     "",      # supplied by httpx t.me scraper
        "bio":            "",      # supplied by httpx t.me scraper
        "follower_count": follower_count,
        "like_count":     0,       # aggregated from posts in _apply_refresh
        "post_count":     post_count_estimate,
        "_posts":         posts,
    }


async def run_once(arg: dict):
    arg = dict(arg)
    username = arg["username"].lstrip("@")
    _wu = _load_worker_utils()
    async with async_playwright() as pw:
        # headless=False — Telegram Web K requires a real rendering context.
        # force_persistent=True — bypass state-file; Telegram auth is in IndexedDB
        #                         which is NOT captured by storage_state JSON.
        # --window-position moves the window off-screen so the user never sees it.
        context, _browser = await _wu.launch_context(
            pw, platform="telegram", headless=False,
            locale="ru-RU", force_persistent=True,
        )
        page = context.pages[0] if context.pages else await context.new_page()
        try:
            return await _run_with_page(username, page, _wu)
        finally:
            await _wu.close_context(context, _browser)


def _write_response(payload: dict) -> None:
    from platforms.worker_json_stdout import write_json_line

    write_json_line(payload)


async def daemon_main() -> None:
    _wu = _load_worker_utils()
    async with async_playwright() as pw:
        context, _browser = await _wu.launch_context(
            pw, platform="telegram", headless=False,
            locale="ru-RU", force_persistent=True,
        )
        page = context.pages[0] if context.pages else await context.new_page()
        try:
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
                    username = str(payload.get("username", "")).lstrip("@")
                    result = await _run_with_page(username, page, _wu)
                except BaseException as exc:
                    _write_response({"error": f"Ошибка worker: {exc}"})
                    continue
                _write_response(result)
        finally:
            await _wu.close_context(context, _browser)


if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "--daemon":
        asyncio.run(daemon_main())
    else:
        if len(sys.argv) < 2:
            _write_response({"error": "Отсутствует payload"})
            sys.exit(1)
        try:
            one_payload = json.loads(sys.argv[1])
        except Exception:
            _write_response({"error": "Невалидный JSON payload"})
            sys.exit(1)
        _write_response(asyncio.run(run_once(one_payload)))
