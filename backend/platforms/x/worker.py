"""
Standalone subprocess — fetches X (Twitter) profile data via x.com.
Invoked by platforms/x/scraper.py as:
    python x/worker.py '{"username": "handle"}'

Uses the shared persistent Chrome profile. Requires an active X session
(log in once via Settings → «Войти в X»).

Extracts: display name, follower/following count, bio, avatar, recent tweets
with view counts and likes.
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
    """'1.2M' / '88.4K' / '1 234 567' / '1,234' → int."""
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
        if (href.includes('/i/flow/login') || href.includes('x.com/login') ||
            href.includes('twitter.com/login')) return false;
        if (document.querySelector('[data-testid="loginButton"]')) return false;
        return !!(
            document.querySelector('[data-testid="SideNav_AccountSwitcher_Button"]') ||
            document.querySelector('[data-testid="AppTabBar_Home_Link"]')            ||
            document.querySelector('[data-testid="primaryColumn"]')
        );
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


async def _run_with_page(username: str, page, _wu) -> dict:
    if True:

        # ── 1. Navigate ───────────────────────────────────────────────────────
        print(f"[x_worker] navigating to @{username}", file=sys.stderr)
        await page.goto(
            f"https://x.com/{username}",
            wait_until="domcontentloaded",
            timeout=NAV_TIMEOUT,
        )
        await _wu.wait_for_anti_bot_clear(page, platform="x")

        # ── 2. Wait for page to settle (profile or login redirect) ────────────
        print("[x_worker] waiting for page to settle…", file=sys.stderr)
        try:
            await page.wait_for_function(
                """() => {
                    const href = window.location.href;
                    if (href.includes('/i/flow/login') || href.includes('/login')) return true;
                    if (document.querySelector('[data-testid="loginButton"]'))       return true;
                    if (document.querySelector('[data-testid="UserName"]'))          return true;
                    if (document.querySelector('[data-testid="error-detail"]'))      return true;
                    return false;
                }""",
                timeout=30_000,
            )
        except Exception:
            missing = await page.evaluate(
                """() => {
                    const txt = (document.body?.innerText || '').toLowerCase();
                    return txt.includes("this account doesn") || txt.includes("this account does not exist");
                }""",
            )
            if missing:
                return {"error": f"Профиль X @{username} не найден."}
            return {"error": "X не загрузился — проверь подключение."}

        # ── 3. Check login ────────────────────────────────────────────────────
        if not await page.evaluate(_LOGGED_IN_JS):
            return {
                "error": (
                    "X требует авторизации — нажмите «Войти в X» "
                    "в настройках приложения."
                )
            }

        # ── 4. Wait for profile header ────────────────────────────────────────
        try:
            await page.wait_for_selector('[data-testid="UserName"]', timeout=LOAD_TIMEOUT)
        except Exception:
            return {"error": f"Профиль X @{username} не найден."}

        await page.wait_for_timeout(2000)

        # ── 5. Extract profile stats ──────────────────────────────────────────
        info = await page.evaluate(
            """(username) => {
                function countFromEl(el) {
                    if (!el) return '';
                    for (const s of el.querySelectorAll('span')) {
                        const t = (s.textContent || '').trim()
                                    .replace(/[\\u00a0\\u202f]/g, '');
                        if (t && /^[\\d,.]+[KkMmBb]?$/.test(t.replace(/\\s/g, '')))
                            return t;
                    }
                    return '';
                }

                // Display name — first leaf span in UserName that isn't @handle
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

                // Follower / following — link hrefs are /{username}/followers etc.
                const col = document.querySelector('[data-testid="primaryColumn"]') || document;
                const followerLink  = col.querySelector(`a[href="/${username}/followers"]`) ||
                                      col.querySelector(`a[href="/${username}/verified_followers"]`);
                const followingLink = col.querySelector(`a[href="/${username}/following"]`);
                const followers = countFromEl(followerLink);
                const following = countFromEl(followingLink);

                // Post count ("X Posts" text near profile header)
                let postCount = '';
                const postsMatch = (col.textContent || '').match(
                    /(\\d[\\d,. ]*[KkMmBb]?)\\s*(?:Posts?|Tweets?|публикаций|твитов)/i
                );
                if (postsMatch) postCount = postsMatch[1].replace(/\\s/g, '');

                // Bio
                const bioEl = document.querySelector('[data-testid="UserDescription"]');
                const bio   = bioEl ? bioEl.innerText.trim() : '';

                // Avatar
                let avatar = '';
                const avatarImg =
                    document.querySelector(`a[href="/${username}/photo"] img`) ||
                    document.querySelector('[data-testid^="UserAvatar-Container"] img');
                if (avatarImg) {
                    avatar = (avatarImg.src || '')
                        .replace('_normal.', '_400x400.')
                        .replace('_200x200.', '_400x400.');
                }

                return { displayName, followers, following, postCount, bio, avatar };
            }""",
            username,
        )

        display_name    = info.get("displayName", "").strip() or username
        follower_count  = _parse_count(info.get("followers", ""))
        following_count = _parse_count(info.get("following", ""))
        post_count_raw  = _parse_count(info.get("postCount", "")) or None
        avatar_url      = info.get("avatar", "")
        bio             = info.get("bio", "")
        print(
            f"[x_worker] @{username}: {display_name!r}, "
            f"{follower_count} followers, post_count={post_count_raw}",
            file=sys.stderr,
        )

        # ── 6. Scroll to load more tweets ─────────────────────────────────────
        for _ in range(3):
            await page.keyboard.press("End")
            await page.wait_for_timeout(1200)

        # ── 7. Extract tweets ─────────────────────────────────────────────────
        posts_raw = await page.evaluate("""
            () => {
                // Extract a numeric stat from a data-testid element.
                function statText(article, testid) {
                    const el = article.querySelector(`[data-testid="${testid}"]`);
                    if (!el) return '0';
                    // aria-label "123 Likes" / "1 ответ"
                    const label = el.getAttribute('aria-label') || '';
                    const mL = label.match(/^([\\d][\\d\\s,.]*)/);
                    if (mL) return mL[1].replace(/\\s/g, '').trim();
                    // Fallback: find deepest numeric span
                    return numericSpan(el);
                }

                // Find the first span whose entire text is a number (possibly with K/M/B suffix).
                function numericSpan(root) {
                    for (const s of [...root.querySelectorAll('span')].reverse()) {
                        const t = (s.textContent || '').trim();
                        if (t && /^[\\d,.]+[KkMmBb]?$/.test(t)) return t;
                    }
                    return '0';
                }

                // View count extraction — tries several strategies because X shows
                // view counts differently for own tweets vs. others' tweets:
                //   • Own tweets:    data-testid="analyticsButton" with chart icon + count
                //   • Others' tweets: inline stats row or group aria-label
                function getViews(article) {
                    // 1. analyticsButton (own tweets or new public view counter)
                    const analBtn = article.querySelector('[data-testid="analyticsButton"]');
                    if (analBtn) {
                        const v = numericSpan(analBtn);
                        if (v !== '0') return v;
                        // aria-label may hold "N views" or just be descriptive
                        const lbl = analBtn.getAttribute('aria-label') || '';
                        const m = lbl.match(/([\\d][\\d\\s,.]*[KkMmBb]?)\\s*(?:view|просмотр)/i);
                        if (m) return m[1].replace(/\\s/g, '');
                    }

                    // 2. Group role="group" aria-label contains "N views"
                    //    X renders: "N Replies, N Reposts, N Likes, N Bookmarks, N views"
                    for (const grp of article.querySelectorAll('[role="group"][aria-label]')) {
                        const lbl = grp.getAttribute('aria-label') || '';
                        const m = lbl.match(/([\\d][\\d\\s,.]*[KkMmBb]?)\\s*(?:view|просмотр)/i);
                        if (m) return m[1].replace(/\\s/g, '');
                    }

                    // 3. <a href="…/analytics"> link contains the view count span
                    const aLink = article.querySelector('a[href*="/analytics"]');
                    if (aLink) {
                        const v = numericSpan(aLink);
                        if (v !== '0') return v;
                    }

                    // 4. Any span whose aria-label mentions "views" directly
                    for (const el of article.querySelectorAll('[aria-label]')) {
                        const lbl = (el.getAttribute('aria-label') || '').toLowerCase();
                        if (lbl.includes('view') || lbl.includes('просмотр')) {
                            const m = lbl.match(/([\\d][\\d\\s,.]*[KkMmBb]?)/);
                            if (m) return m[1].replace(/\\s/g, '');
                        }
                    }

                    return '0';
                }

                const results = [];
                const seen    = new Set();
                const MAX_TWEETS = 40;
                for (const article of document.querySelectorAll('article[data-testid="tweet"]')) {
                    if (results.length >= MAX_TWEETS) break;
                    try {
                        const timeEl = article.querySelector('time');
                        const link   = timeEl ? timeEl.closest('a') : null;
                        const href   = link ? link.getAttribute('href') : '';
                        const m      = (href || '').match(/\\/status\\/(\\d+)/);
                        if (!m) continue;
                        const id = m[1];
                        if (seen.has(id)) continue;
                        seen.add(id);

                        const textEl = article.querySelector('[data-testid="tweetText"]');
                        const text   = textEl ? textEl.innerText.trim().slice(0, 500) : '';
                        const ts     = timeEl ? timeEl.getAttribute('datetime') : '';

                        let thumb = '';
                        const imgEl =
                            article.querySelector('img[src*="pbs.twimg.com/media"]') ||
                            article.querySelector('[data-testid="tweetPhoto"] img');
                        if (imgEl) thumb = imgEl.src || '';

                        results.push({
                            id,
                            text,
                            ts:      ts || '',
                            thumb,
                            likes:   statText(article, 'like'),
                            views:   getViews(article),
                            replies: statText(article, 'reply'),
                        });
                    } catch (_) {}
                }
                return results;
            }
        """)

    # ── 8. Post-process ───────────────────────────────────────────────────────
    posts = []
    for p in posts_raw:
        tweet_id = str(p.get("id", "")).strip()
        if not tweet_id:
            continue
        ts = p.get("ts", "")
        posted_at = None
        if ts:
            try:
                posted_at = datetime.fromisoformat(ts.replace("Z", "+00:00")).isoformat()
            except Exception:
                pass
        posts.append({
            "external_id":   tweet_id,
            "description":   p.get("text", ""),
            "thumbnail_url": p.get("thumb", ""),
            "post_url":      f"https://x.com/{username}/status/{tweet_id}",
            "view_count":    _parse_count(p.get("views", "0")),
            "like_count":    _parse_count(p.get("likes", "0")),
            "comment_count": _parse_count(p.get("replies", "0")),
            "share_count":   0,
            "posted_at":     posted_at,
        })

    print(f"[x_worker] extracted {len(posts)} tweets", file=sys.stderr)

    return {
        "display_name":    display_name,
        "avatar_url":      avatar_url,
        "bio":             bio,
        "follower_count":  follower_count,
        "following_count": following_count,
        "like_count":      0,   # aggregated from posts in _apply_refresh
        "post_count":      post_count_raw,  # None → preserve DB value
        "_posts":          posts,
    }


async def run_once(arg: dict) -> dict:
    username = arg["username"].lstrip("@")
    _wu = _load_worker_utils()
    async with async_playwright() as pw:
        context, _browser = await _wu.launch_context(
            pw, platform="x", locale="en-US",
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
            pw, platform="x", locale="en-US",
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
                except (KeyboardInterrupt, SystemExit):
                    raise
                except asyncio.CancelledError:
                    raise
                except BaseException as exc:
                    # Иначе при падении Playwright процесс демона умирает без строки в stdout →
                    # «Worker не вернул ответ» на стороне Django.
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
