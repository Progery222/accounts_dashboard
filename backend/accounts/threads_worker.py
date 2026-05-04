"""
Standalone subprocess — fetches Threads profile data via threads.net.
Invoked by accounts/scrapers.py as:
    python threads_worker.py '{"username": "handle"}'

Uses the shared persistent Chrome profile. Requires an active Threads session
(log in once via Settings → «Войти в Threads»).

Public profiles (without auth) expose name/bio/followers — the worker works
in degraded mode if not logged in (no posts). Full post data requires auth.
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
    if not text:
        return 0
    text = str(text).strip()
    text = text.replace('\xa0', '').replace('\u202f', '').replace(' ', '')
    m = re.match(r'^([\d]+(?:[.,][\d]+)?)\s*([KMBkmb]?)$', text.replace(',', '.'))
    if m:
        try:
            num  = float(m.group(1))
            mult = {'K': 1_000, 'M': 1_000_000, 'B': 1_000_000_000}.get(m.group(2).upper(), 1)
            return int(num * mult)
        except ValueError:
            pass
    digits = re.sub(r'[^\d]', '', text)
    return int(digits) if digits else 0


# ── Login check JS ────────────────────────────────────────────────────────────

_LOGGED_IN_JS = """
    () => {
        const href = window.location.href;
        if (href.includes('/login')) return false;
        // Login form visible
        if (document.querySelector('input[type="password"]') &&
            (document.querySelector('input[autocomplete="email"]') ||
             document.querySelector('input[autocomplete="username"]'))) return false;
        // Logged-in indicators: compose button or account nav present
        return !!(
            document.querySelector('[aria-label*="New thread"]')    ||
            document.querySelector('[aria-label*="Новый тред"]')    ||
            document.querySelector('a[href="/"][role="link"]')      ||
            document.querySelector('[data-pressable-container]')
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
        context, _browser = await _wu.launch_context(
            pw, platform="threads", locale="en-US",
        )
        page = context.pages[0] if context.pages else await context.new_page()

        # ── 1. Navigate ───────────────────────────────────────────────────────
        # Threads migrated to threads.com; cookies from that domain won't be sent
        # to threads.net, so we always navigate to threads.com.
        print(f"[threads_worker] navigating to @{username}", file=sys.stderr)
        await page.goto(
            f"https://www.threads.com/@{username}",
            wait_until="domcontentloaded",
            timeout=NAV_TIMEOUT,
        )

        # ── 2. Wait for page to settle (profile or login) ─────────────────────
        print("[threads_worker] waiting for page to settle…", file=sys.stderr)
        try:
            await page.wait_for_function(
                """() => {
                    const href = window.location.href;
                    if (href.includes('/login')) return true;
                    // Profile header or modal appeared
                    if (document.querySelector('h1'))             return true;
                    if (document.querySelector('header'))         return true;
                    if (document.querySelector('[role="main"]'))  return true;
                    return false;
                }""",
                timeout=30_000,
            )
        except Exception:
            await _wu.close_context(context, _browser)
            print(json.dumps({"error": "Threads не загрузился — проверь подключение."}))
            sys.exit(1)

        # Extra time for JS to render
        await page.wait_for_timeout(2500)

        # ── 3. Check login (non-blocking: public profiles still partially work) ─
        logged_in = await page.evaluate(_LOGGED_IN_JS)
        print(f"[threads_worker] logged_in={logged_in}", file=sys.stderr)
        if not logged_in:
            print("[threads_worker] not logged in — profile stats only", file=sys.stderr)

        # ── 4. Extract profile stats ──────────────────────────────────────────
        info = await page.evaluate(
            """(username) => {
                // ── Display name ───────────────────────────────────────────
                let displayName = '';
                const h1 = document.querySelector('h1');
                if (h1) displayName = h1.textContent.trim();

                // ── Follower count ─────────────────────────────────────────
                // Threads uses href="/@username/followers" pattern
                let followers = '';
                const followerLink =
                    document.querySelector(`a[href="/@${username}/followers"]`) ||
                    document.querySelector('a[href*="/followers"]');
                if (followerLink) {
                    const t = followerLink.textContent.trim();
                    const m = t.match(/^(\\d[\\d,. ]*[KkMmBb]?)/);
                    if (m) followers = m[1].replace(/\\s/g, '');
                    // Also look inside spans
                    if (!followers) {
                        for (const s of followerLink.querySelectorAll('span')) {
                            const st = (s.textContent || '').trim();
                            if (st && /^\\d/.test(st)) { followers = st; break; }
                        }
                    }
                }
                // Fallback: text pattern anywhere
                if (!followers) {
                    const bodyText = document.body.innerText || '';
                    const m = bodyText.match(
                        /(\\d[\\d,.]*[KkMmBb]?)\\s*(?:followers?|подписчик)/i
                    );
                    if (m) followers = m[1];
                }

                // ── Post count — "2.3K Threads" text near the profile header ──
                let postCount = '';
                const bodyText = document.body.innerText || '';
                const pcm = bodyText.match(
                    /(\\d[\\d,.]*[KkMmBb]?)\\s*Threads?/i
                );
                if (pcm) postCount = pcm[1];

                // ── Bio ────────────────────────────────────────────────────
                let bio = '';
                const metaDesc = document.querySelector('meta[name="description"]');
                if (metaDesc) {
                    bio = metaDesc.getAttribute('content') || '';
                    bio = bio.replace(/\\s*[-–•·]\\s*\\d.*?followers?.*$/i, '').trim();
                }

                // ── Avatar ─────────────────────────────────────────────────
                let avatar = '';
                for (const img of document.querySelectorAll('img')) {
                    const src = img.src || '';
                    // Threads/Instagram CDN URLs
                    if ((src.includes('cdninstagram') || src.includes('fbcdn')) &&
                        !src.includes('/t51.')) {   // skip post thumbnails
                        avatar = src; break;
                    }
                }

                return { displayName, followers, postCount, bio, avatar };
            }""",
            username,
        )

        display_name   = info.get("displayName", "").strip() or username
        follower_count = _parse_count(info.get("followers", ""))
        post_count_val = _parse_count(info.get("postCount", "")) or None
        avatar_url     = info.get("avatar", "")
        bio            = info.get("bio", "")
        print(
            f"[threads_worker] @{username}: {display_name!r}, "
            f"{follower_count} followers, post_count={post_count_val}",
            file=sys.stderr,
        )

        posts_raw = []
        if logged_in:
            # ── 5. Scroll to load posts ───────────────────────────────────────
            for _ in range(3):
                await page.keyboard.press("End")
                await page.wait_for_timeout(1200)

            # ── 6. Extract posts ──────────────────────────────────────────────
            posts_raw = await page.evaluate(
                """(username) => {
                    function getCount(el) {
                        if (!el) return '0';
                        const label = el.getAttribute('aria-label') || '';
                        const mL = label.match(/^([\\d][\\d\\s,.]*)/);
                        if (mL) return mL[1].replace(/\\s/g, '');
                        for (const s of [...el.querySelectorAll('span')].reverse()) {
                            const t = (s.textContent || '').trim();
                            if (t && /^[\\d,.]+[KkMmBb]?$/.test(t)) return t;
                        }
                        return '0';
                    }

                    // Extract view count for a post container.
                    // Threads shows "16.4M views" / "16,464,791 views" / "16 464 791 views"
                    // (space = thousands separator in Russian locale).
                    function getViews(el) {
                        // 1. aria-label "N views" / "N просмотров" on any child
                        for (const node of el.querySelectorAll('[aria-label]')) {
                            const lbl = node.getAttribute('aria-label') || '';
                            // Capture digits + spaces/commas/dots + optional K/M/B suffix
                            const m = lbl.match(/([\d][\d\s,.]*[KkMmBb]?)\s*(?:views?|просмотр)/i);
                            if (m) return m[1].replace(/[\s,]/g, '');
                        }
                        // 2. Visible text in the post: "16.4M views" / "16 464 791 views"
                        const text = el.innerText || '';
                        const m = text.match(/([\d][\d\s,.]*[KkMmBb]?)\s*views/i);
                        if (m) return m[1].replace(/[\s,]/g, '');
                        return '0';
                    }

                    const results = [];
                    const seen    = new Set();

                    // Each post/thread is inside an article or a pressable container
                    const containers = document.querySelectorAll(
                        'article, div[role="article"], [data-pressable-container="true"]'
                    );

                    for (const el of containers) {
                        try {
                            // Post ID from permalink
                            let postId = '', postUrl = '';
                            for (const a of el.querySelectorAll('a[href*="/post/"], a[href*="/t/"]')) {
                                const href = a.getAttribute('href') || '';
                                const m    = href.match(/\/post\/([^/?#]+)/) ||
                                             href.match(/\/t\/([^/?#]+)/);
                                if (m) {
                                    postId  = m[1];
                                    postUrl = a.href || `https://www.threads.com${href}`;
                                    break;
                                }
                            }
                            if (!postId || seen.has(postId)) continue;
                            seen.add(postId);

                            // Text — Threads uses dir="auto" spans for text
                            const textSpans = el.querySelectorAll('span[dir="auto"]');
                            let text = '';
                            for (const s of textSpans) {
                                const t = (s.innerText || '').trim();
                                if (t.length > text.length) text = t;
                            }
                            text = text.slice(0, 500);

                            // Timestamp
                            let ts = '';
                            const timeEl = el.querySelector('time');
                            if (timeEl) ts = timeEl.getAttribute('datetime') || '';

                            // Thumbnail
                            let thumb = '';
                            for (const img of el.querySelectorAll('img')) {
                                const src = img.src || '';
                                if (src.includes('/t51.') || src.includes('pbs.twimg')) {
                                    thumb = src; break;
                                }
                            }

                            // Like count — button near a heart SVG
                            let likes = '0';
                            for (const btn of el.querySelectorAll('button, [role="button"]')) {
                                const svgPath = (btn.innerHTML || '');
                                // Threads heart SVG paths contain characteristic d values
                                if (/M12.*heart|M8.*24|M12.*L8/i.test(svgPath) ||
                                    (btn.getAttribute('aria-label') || '').toLowerCase().includes('like')) {
                                    likes = getCount(btn);
                                    break;
                                }
                            }

                            // Reply count
                            let replies = '0';
                            for (const btn of el.querySelectorAll('button, [role="button"]')) {
                                const label = (btn.getAttribute('aria-label') || '').toLowerCase();
                                if (label.includes('repl') || label.includes('ответ') ||
                                    label.includes('comment')) {
                                    replies = getCount(btn); break;
                                }
                            }

                            results.push({ id: postId, url: postUrl, text, ts, thumb,
                                           likes, replies, views: getViews(el) });
                        } catch (_) {}
                    }
                    return results;
                }""",
                username,
            )

        await _wu.close_context(context, _browser)

    # ── 7. Post-process ───────────────────────────────────────────────────────
    posts = []
    for p in posts_raw:
        post_id = str(p.get("id", "")).strip()
        if not post_id:
            continue
        ts = p.get("ts", "")
        posted_at = None
        if ts:
            try:
                posted_at = datetime.fromisoformat(ts.replace("Z", "+00:00")).isoformat()
            except Exception:
                pass
        posts.append({
            "external_id":   post_id,
            "description":   p.get("text", ""),
            "thumbnail_url": p.get("thumb", ""),
            "post_url":      p.get("url", f"https://www.threads.com/t/{post_id}"),
            "view_count":    _parse_count(p.get("views", "0")),
            "like_count":    _parse_count(p.get("likes", "0")),
            "comment_count": _parse_count(p.get("replies", "0")),
            "share_count":   0,
            "posted_at":     posted_at,
        })

    print(f"[threads_worker] extracted {len(posts)} posts", file=sys.stderr)

    print(json.dumps({
        "display_name":    display_name,
        "avatar_url":      avatar_url,
        "bio":             bio,
        "follower_count":  follower_count,
        "following_count": 0,
        "like_count":      0,   # aggregated from posts in _apply_refresh
        "post_count":      post_count_val,
        "_posts":          posts,
    }))


asyncio.run(main())
