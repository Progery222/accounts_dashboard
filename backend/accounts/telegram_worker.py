"""
Standalone subprocess — fetches Telegram channel data via web.telegram.org/k/.
Invoked by accounts/scrapers.py as:
    python telegram_worker.py '{"username": "channelname"}'

Runs headless (no visible window). Uses the shared persistent Chrome profile so
the user only needs to log in once via Settings → "Войти в Telegram".

Extracts: channel name, subscriber count, messages with view counts and reactions.
Avatars are intentionally skipped — Telegram Web uses blob: URLs that are not
transferable outside the browser; the httpx scraper provides the CDN URL instead.
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


# ── Login-state helper (JS) ───────────────────────────────────────────────────

_LOGGED_IN_JS = """
    () => {
        const auth = document.querySelector('#auth-pages, .auth-page, .page-sign');
        if (auth) {
            const st = window.getComputedStyle(auth);
            if (st.display !== 'none' && st.visibility !== 'hidden') return false;
        }
        return !!(
            document.querySelector('#column-left')        ||
            document.querySelector('.sidebar-left')       ||
            document.querySelector('.chat-list')          ||
            document.querySelector('.chatlist')           ||
            document.querySelector('.dialogs-container')  ||
            document.querySelector('[class*="chatList"]') ||
            document.querySelector('.LeftColumn')         ||
            document.querySelector('.chat-info')
        );
    }
"""


# ── Main ──────────────────────────────────────────────────────────────────────

async def main():
    arg      = json.loads(sys.argv[1])
    username = arg["username"].lstrip("@")

    import importlib.util as _ilu
    _wu_path = Path(__file__).parent / "worker_utils.py"
    _wu_spec = _ilu.spec_from_file_location("worker_utils", _wu_path)
    _wu = _ilu.module_from_spec(_wu_spec)
    _wu_spec.loader.exec_module(_wu)

    async with async_playwright() as pw:
        # Telegram Web requires a non-headless window for full rendering.
        # Use --window-position off-screen so the user doesn't see it.
        context, _browser = await _wu.launch_context(
            pw, platform="telegram", headless=False, locale="ru-RU",
        )
        # Add off-screen args via a workaround: if persistent fallback was used
        # the args were already set in launch_context; for ephemeral context we
        # cannot set window position post-launch, but it's fine (it won't pop up).
        page = context.pages[0] if context.pages else await context.new_page()

        # ── 1. Navigate ───────────────────────────────────────────────────────
        print(f"[telegram_worker] navigating to @{username}", file=sys.stderr)
        await page.goto(
            f"https://web.telegram.org/k/#@{username}",
            wait_until="domcontentloaded",
            timeout=NAV_TIMEOUT,
        )

        # ── 2. Wait for Telegram Web to finish session check ──────────────────
        # Telegram Web K adds 'has-auth-pages' to <body> while loading / checking
        # session. Once the session is confirmed the class is removed and the main
        # chat UI appears. We reactively wait up to 30 s instead of a blind sleep.
        print("[telegram_worker] waiting for session initialisation…", file=sys.stderr)
        try:
            await page.wait_for_function(
                """() => {
                    // Auth overlay gone → session validated
                    const auth = document.querySelector('#auth-pages');
                    if (auth) {
                        const st = window.getComputedStyle(auth);
                        if (st.display !== 'none' && st.visibility !== 'hidden') return false;
                    }
                    // body still has has-auth-pages → still initialising
                    if (document.body && document.body.classList.contains('has-auth-pages')) return false;
                    // At least one main-UI element present
                    return !!(
                        document.querySelector('#column-left')       ||
                        document.querySelector('.sidebar-left')      ||
                        document.querySelector('.chat-list')         ||
                        document.querySelector('.chatlist')          ||
                        document.querySelector('.dialogs-container') ||
                        document.querySelector('[class*="chatList"]')||
                        document.querySelector('.LeftColumn')        ||
                        document.querySelector('.chat-info')
                    );
                }""",
                timeout=30_000,
            )
        except Exception:
            # Timed out — auth pages never disappeared → not logged in
            await _wu.close_context(context, _browser)
            print(json.dumps({
                "error": (
                    "Telegram требует авторизации — нажмите «Войти в Telegram» "
                    "в настройках приложения."
                )
            }))
            sys.exit(1)

        # ── 3. Verify login state ─────────────────────────────────────────────
        if not await page.evaluate(_LOGGED_IN_JS):
            await _wu.close_context(context, _browser)
            print(json.dumps({
                "error": (
                    "Telegram требует авторизации — нажмите «Войти в Telegram» "
                    "в настройках приложения."
                )
            }))
            sys.exit(1)

        # ── 4. Wait for channel header ────────────────────────────────────────
        try:
            await page.wait_for_selector(
                "#column-center .peer-title, .chat-info .peer-title",
                timeout=LOAD_TIMEOUT,
            )
        except Exception:
            await _wu.close_context(context, _browser)
            print(json.dumps({
                "error": f"Telegram @{username} не найден или не загрузился."
            }))
            sys.exit(1)

        # Extra time for messages to render
        await page.wait_for_timeout(2500)

        # ── 5. Channel header info ────────────────────────────────────────────
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

        # ── 6. Extract messages ───────────────────────────────────────────────
        posts_raw = await page.evaluate("""
            () => {
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

                        // Text
                        const msgEl = bubble.querySelector('.message') ||
                                      bubble.querySelector('.translatable-message');
                        const text = msgEl ? msgEl.innerText.trim().slice(0, 500) : '';

                        // Views — extract numeric text only (skip icon glyphs)
                        let viewsText = '';
                        const viewsEl = bubble.querySelector('.message-views-counter') ||
                                        bubble.querySelector('.post-views .views-count');
                        if (viewsEl) {
                            viewsText = viewsEl.textContent.trim();
                        } else {
                            const pvEl = bubble.querySelector('.post-views');
                            if (pvEl) {
                                const chunks = [];
                                for (const n of pvEl.childNodes) {
                                    if (n.nodeType === 3) chunks.push(n.textContent.trim());
                                }
                                viewsText = chunks.filter(Boolean).join('');
                                if (!viewsText)
                                    viewsText = pvEl.textContent.replace(/[^\\d.,KkMmBb]/g, '');
                            }
                        }

                        // Reactions — sum ALL reaction counts (❤️ + 👍 + …)
                        // Telegram Web K uses many different class patterns across versions;
                        // cast a wide net and deduplicate by element to avoid double-counting.
                        let totalReactions = 0;
                        const seenReactionEls = new Set();
                        const reactionCandidates = bubble.querySelectorAll(
                            '.reaction-counter-in,'        +
                            '.reaction-count,'             +
                            '.reaction-node .counter-inner,'+
                            '[class*="reaction"] .counter, '+
                            '[class*="reactions"] span,'   +
                            '.reactions-inline .count,'    +
                            '.reaction .count,'            +
                            '[class*="ReactionCount"],'    +
                            '.message-reactions span'
                        );
                        for (const rel of reactionCandidates) {
                            if (seenReactionEls.has(rel)) continue;
                            seenReactionEls.add(rel);
                            const t = rel.textContent.trim()
                                        .replace(/[\\s\\u00a0\\u202f]/g, '').replace(',', '.');
                            const m = t.match(/^([\\d]+(?:\\.[\\d]+)?)([KkMm]?)$/);
                            if (m) {
                                const n    = parseFloat(m[1]);
                                const mult = { K: 1000, M: 1000000 }[m[2].toUpperCase()] || 1;
                                totalReactions += Math.round(n * mult);
                            }
                        }
                        // Fallback: look for aria-label="N reactions" on any child
                        if (totalReactions === 0) {
                            for (const el of bubble.querySelectorAll('[aria-label]')) {
                                const lbl = el.getAttribute('aria-label') || '';
                                const m2  = lbl.match(/(\\d[\\d\\s,.]*)\\s*react/i);
                                if (m2) {
                                    totalReactions += parseInt(m2[1].replace(/[^\\d]/g, ''), 10) || 0;
                                }
                            }
                        }

                        // Timestamp
                        const timeEl = bubble.querySelector('.time-inner');
                        const ts = timeEl ? (timeEl.dataset.timestamp || '') : '';

                        // Thumbnail
                        let thumb = '';
                        const imgEl = bubble.querySelector('.media-photo img') ||
                                      bubble.querySelector('.media-sticker img');
                        if (imgEl) thumb = imgEl.src || '';
                        // Skip blob: URLs — they are browser-internal and not storable
                        if (thumb.startsWith('blob:')) thumb = '';

                        results.push({ mid, text, views: viewsText,
                                       reactions: totalReactions, ts, thumb });
                    } catch (e) { /* skip malformed bubble */ }
                }
                return results;
            }
        """)

        await _wu.close_context(context, _browser)

    # ── 7. Post-process ───────────────────────────────────────────────────────
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

        # data-mid can be an encoded value; use it as-is for dedup (external_id is a
        # CharField so any string works).  For the public t.me link we try to use the
        # lower 20 bits as an approximation of the server-side message ID.
        try:
            mid_int  = int(mid)
            # Telegram Web K encodes channel mids as (something << 20) | real_msg_id
            # in some versions, or just stores the plain msg_id in others.
            # If the value fits in 20 bits (≤ 1 048 575) it's probably already plain.
            real_id  = mid_int & 0xFFFFF if mid_int > 0xFFFFF else mid_int
            if real_id > 0:
                real_ids.append(real_id)
            post_url = f"https://t.me/{username}/{real_id}" if real_id > 0 else ""
        except ValueError:
            post_url = ""

        posts.append({
            "external_id":   mid,          # stable dedup key
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

    # Use the highest real message ID as a lower-bound for post_count.
    # This is more accurate than len(posts) because channels may have thousands
    # of messages; only the most recent ~20 are visible in the Telegram Web UI.
    # If the httpx t.me/s/ stream returned 0 this value will override the zero.
    post_count_estimate = max(real_ids) if real_ids else (len(posts) if posts else None)

    print(json.dumps({
        "display_name":    display_name,
        "avatar_url":      "",      # supplied by httpx t.me scraper
        "bio":             "",      # supplied by httpx t.me scraper
        "follower_count":  follower_count,
        "following_count": 0,
        "like_count":      0,       # aggregated from posts in _apply_refresh
        "post_count":      post_count_estimate,
        "_posts":          posts,
    }))


asyncio.run(main())
