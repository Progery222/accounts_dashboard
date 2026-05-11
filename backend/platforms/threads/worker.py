"""
Standalone subprocess — fetches Threads profile data via threads.net.
Invoked by platforms/threads/scraper.py as:
    python threads/worker.py '{"username": "handle"}'

Uses the shared persistent Chrome profile. Requires an active Threads session
(log in once via Settings → «Войти в Threads»).

Public profiles (without auth) expose name/bio/followers — the worker works
in degraded mode if not logged in (no posts). Full post data requires auth.
"""
import asyncio
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from playwright.async_api import async_playwright

from platforms.profile_unavailable import PROFILE_UNAVAILABLE_MARK

NAV_TIMEOUT  = 30_000   # ms
LOAD_TIMEOUT = 20_000   # ms
POST_OPEN_TIMEOUT_MS = int(os.getenv("THREADS_POST_OPEN_TIMEOUT_MS", "28000") or "28000")
POST_VIEWS_MAX_POSTS = int(os.getenv("THREADS_POST_VIEWS_MAX_POSTS", "28") or "28")
POST_DELAY_MS = int(os.getenv("THREADS_POST_DELAY_MS", "1450") or "1450")
POST_RETRY_CLICKS = int(os.getenv("THREADS_POST_RETRY_CLICKS", "4") or "4")
POST_VIEWS_DOM_RESCAN_MS = int(os.getenv("THREADS_POST_VIEWS_DOM_RESCAN_MS", "2400") or "2400")


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


def _extract_post_code_from_url(url: str) -> str:
    if not url:
        return ""
    m = re.search(r"/post/([A-Za-z0-9_-]{6,})", str(url))
    if m:
        return m.group(1)
    m = re.search(r"/t/([A-Za-z0-9_-]{6,})", str(url))
    return m.group(1) if m else ""


def _collect_post_views_from_json(payload, out: dict[str, int]) -> None:
    """Рекурсивно собирает post_code -> view_count из JSON-ответов Threads."""
    stack = [payload]
    while stack:
        cur = stack.pop()
        if isinstance(cur, list):
            stack.extend(cur)
            continue
        if not isinstance(cur, dict):
            continue

        view_val = 0
        for key in (
            "view_count",
            "video_view_count",
            "video_play_count",
            "play_count",
            "views",
            "total_view_count",
            "impression_count",
            "play_count_num",
            "video_view_count_string",
        ):
            if key in cur:
                view_val = max(view_val, _parse_count(cur.get(key)))

        if view_val > 0:
            candidates: set[str] = set()
            for key in ("code", "shortcode", "post_code", "thread_code"):
                val = str(cur.get(key) or "").strip()
                if re.match(r"^[A-Za-z0-9_-]{6,}$", val):
                    candidates.add(val)
            for key in ("permalink", "url", "post_url", "thread_url"):
                code = _extract_post_code_from_url(str(cur.get(key) or ""))
                if code:
                    candidates.add(code)
            for code in candidates:
                prev = int(out.get(code) or 0)
                if view_val > prev:
                    out[code] = view_val

        for v in cur.values():
            if isinstance(v, (dict, list)):
                stack.append(v)


async def _capture_response_post_views(response, out: dict[str, int]) -> None:
    """Пытается вытащить views из network JSON, не открывая посты отдельно."""
    try:
        url = (response.url or "").lower()
    except Exception:
        url = ""
    if not url:
        return
    if (
        "/graphql/" not in url
        and "threads" not in url
        and "barcelona" not in url
        and "/api/" not in url
    ):
        return

    try:
        ctype = (response.headers or {}).get("content-type", "").lower()
    except Exception:
        ctype = ""
    if "json" not in ctype and "graphql" not in url:
        return

    try:
        payload = await response.json()
    except Exception:
        return

    before = len(out)
    _collect_post_views_from_json(payload, out)
    after = len(out)
    if after > before:
        print(
            f"[threads_worker] network views map +{after - before} (total={after})",
            file=sys.stderr,
        )


def _extract_views_from_text_blob(text: str) -> int:
    if not text:
        return 0
    m = re.search(r"([\d][\d\s,.]*[KkMmBb]?)\s*(?:views?|просмотров?)\b", text, re.I)
    if not m:
        return 0
    return _parse_count(m.group(1))


async def _click_retry_on_error_page(page) -> bool:
    """Нажимает «Повторить попытку» на странице поста Threads, если кнопка есть."""
    try:
        return await page.evaluate(
            r"""() => {
                const norm = (s) => (s || '').toLowerCase().replace(/\s+/g, ' ').trim();
                const isRetryText = (t) => {
                    const n = norm(t);
                    return n.includes('повторить попытку') || n.includes('try again') || n.includes('retry');
                };
                const nodes = document.querySelectorAll('button, [role="button"], span, div');
                for (const el of nodes) {
                    const t = (el.innerText || el.textContent || '').trim();
                    if (!t || t.length > 64) continue;
                    if (isRetryText(t)) {
                        el.click();
                        return true;
                    }
                }
                return false;
            }"""
        )
    except Exception:
        return False


async def _extract_views_on_open_post(page) -> int:
    """Читает просмотры на уже открытой странице поста (несколько попыток — DOM подгружается)."""
    best = 0
    for attempt in range(5):
        try:
            v = await page.evaluate(
            r"""() => {
                const parseCount = (txt) => {
                    const t = String(txt || '').replace(/\u00a0/g,'').replace(/\u202f/g,'').replace(/\s+/g,'').trim();
                    const m = t.match(/^([\d]+(?:[.,][\d]+)?)\s*([KMBkmb]?)$/);
                    if (m) {
                        const n = parseFloat(m[1].replace(',', '.'));
                        const u = (m[2] || '').toUpperCase();
                        const mult = u === 'K' ? 1e3 : u === 'M' ? 1e6 : u === 'B' ? 1e9 : 1;
                        return Number.isFinite(n) ? Math.round(n * mult) : 0;
                    }
                    const d = t.replace(/[^\d]/g, '');
                    return d ? parseInt(d, 10) : 0;
                };
                const scan = (root) => {
                    if (!root) return 0;
                    // 1) aria-label c "N views/просмотров"
                    for (const n of root.querySelectorAll('[aria-label]')) {
                        const lbl = n.getAttribute('aria-label') || '';
                        const m = lbl.match(/([\d][\d\s,.]*[KkMmBb]?)\s*(?:views?|просмотров?|просмотр(?:ов|а)?)/i);
                        if (m) {
                            const v = parseCount(m[1]);
                            if (v > 0) return v;
                        }
                    }
                    // 2) видимый текст
                    const txt = root.innerText || '';
                    const m = txt.match(/([\d][\d\s,.]*[KkMmBb]?)\s*(?:views?|просмотров?|просмотр(?:ов|а)?)/i);
                    if (m) return parseCount(m[1]);
                    return 0;
                };
                return scan(document.body);
            }"""
            )
        except Exception:
            v = 0
        try:
            best = max(best, int(v or 0))
        except Exception:
            pass
        if best > 0 and attempt >= 1:
            break
        await asyncio.sleep(0.42 if attempt < 4 else 0.0)
    return int(best or 0)


async def _collect_post_views_by_opening_posts(
    page,
    *,
    username: str,
    posts_raw: list[dict],
    network_hints: dict[str, int] | None = None,
) -> dict[str, int]:
    """
    fallback: открываем страницы постов с паузой и ретраем «Повторить попытку».
    Нужно, когда в ленте нет просмотров, либо JSON из сети даёт больше, чем DOM ленты.
    """
    out: dict[str, int] = {}
    if not posts_raw:
        return out
    hints = network_hints or {}

    candidates: list[tuple[str, str]] = []
    seen: set[str] = set()
    for p in posts_raw:
        pid = str(p.get("id") or "").strip()
        if not pid or pid in seen:
            continue
        seen.add(pid)
        dom_views = _parse_count(p.get("views", "0"))
        network_v = int(hints.get(pid, 0) or 0)
        if dom_views > 0 and network_v <= dom_views:
            continue
        purl = str(p.get("url") or "").strip()
        if not purl:
            purl = f"https://www.threads.com/@{username}/post/{pid}"
        candidates.append((pid, purl))
        if len(candidates) >= POST_VIEWS_MAX_POSTS:
            break

    if not candidates:
        return out

    print(
        f"[threads_worker] fallback open-post views: {len(candidates)} candidates",
        file=sys.stderr,
    )
    for idx, (pid, purl) in enumerate(candidates, start=1):
        try:
            await page.goto(purl, wait_until="domcontentloaded", timeout=POST_OPEN_TIMEOUT_MS)
            await asyncio.sleep(1.25)
            try:
                await page.mouse.wheel(0, 420)
            except Exception:
                pass
            await asyncio.sleep(0.35)
            v = await _extract_views_on_open_post(page)
            if v <= 0:
                # Иногда страница роняется на "Произошла ошибка. Повторить попытку позже."
                # Пробуем нажать Retry пару раз.
                for _ in range(POST_RETRY_CLICKS):
                    clicked = await _click_retry_on_error_page(page)
                    if not clicked:
                        break
                    await asyncio.sleep(1.2)
                    v = await _extract_views_on_open_post(page)
                    if v > 0:
                        break
            if v > 0:
                out[pid] = v
                print(f"[threads_worker] post {idx}/{len(candidates)} {pid}: views={v}", file=sys.stderr)
            else:
                print(f"[threads_worker] post {idx}/{len(candidates)} {pid}: views not found", file=sys.stderr)
        except Exception as exc:
            print(f"[threads_worker] post {idx}/{len(candidates)} {pid}: open failed: {exc}", file=sys.stderr)
        await asyncio.sleep(max(0.2, POST_DELAY_MS / 1000.0))
    return out


# ── Login check JS ────────────────────────────────────────────────────────────

_LOGGED_IN_JS = """
    () => {
        const href = window.location.href;
        if (href.includes('/login')) return false;
        if (document.querySelector('input[type="password"]') &&
            (document.querySelector('input[autocomplete="email"]') ||
             document.querySelector('input[autocomplete="username"]'))) return false;
        // Не используем общий [data-pressable-container] — он есть и на публичных профилях.
        return !!(
            document.querySelector('[aria-label*="New thread"]') ||
            document.querySelector('[aria-label*="Новый тред"]') ||
            document.querySelector('[aria-label*="Create"]') ||
            document.querySelector('a[href="/"][aria-label*="Home"]')
        );
    }
"""


async def _fallback_posts_from_page_html(page, username: str) -> list[dict]:
    """Если DOM почти пустой — вытащить id постов из сырого HTML (как запасной слой)."""
    try:
        html = await page.content()
    except Exception:
        return []
    seen: set[str] = set()
    out: list[dict] = []
    for m in re.finditer(r"/post/([A-Za-z0-9_-]+)", html):
        pid = m.group(1)
        if not pid or pid in seen:
            continue
        seen.add(pid)
        out.append({
            "id": pid,
            "url": f"https://www.threads.com/@{username.lstrip('@')}/post/{pid}",
            "text": "",
            "ts": "",
            "thumb": "",
            "likes": "0",
            "replies": "0",
            "views": "0",
        })
        if len(out) >= 80:
            break
    return out


def _threads_body_indicates_profile_removed(body: str) -> bool:
    """Страница вроде threads.com/@user при удалённом / несуществующем профиле (часто 200 OK)."""
    if not body or len(body) < 40:
        return False
    low = body.lower()
    if "not all who wander are lost, but this page is" in low:
        return True
    if "the link's not working" in low and "page is gone" in low:
        return True
    if "ссылка не работает" in low and "страниц" in low:
        return True
    return False


# ── Main ──────────────────────────────────────────────────────────────────────

async def run_once(arg: dict):
    arg = dict(arg)
    username = arg["username"].lstrip("@")

    try:
        _wu = _load_worker_utils()
    except Exception as exc:
        print(f"[threads_worker] ERROR: {exc}", file=sys.stderr)
        from platforms.worker_json_stdout import write_json_line

        write_json_line({"error": str(exc)})
        sys.exit(1)

    async with async_playwright() as pw:
        context, _browser = await _wu.launch_context(
            pw, platform="threads", locale="en-US",
        )
        page = context.pages[0] if context.pages else await context.new_page()
        try:
            return await _run_with_page(username, page, _wu)
        finally:
            await _wu.close_context(context, _browser)


async def _run_with_page(username: str, page, _wu):
    # Initialise all result variables before the async block so the
    # post-processing section at the bottom always has valid references.
    display_name   = username
    follower_count = 0
    post_count_val = None
    avatar_url     = ""
    bio            = ""
    posts_raw      = []
    settle_relaxed = False  # таймаут «ожидания DOM» — не считаем пустой список постов авторитетным
    network_post_views: dict[str, int] = {}

    async def _on_response(resp):
        await _capture_response_post_views(resp, network_post_views)

    page.on("response", lambda resp: asyncio.create_task(_on_response(resp)))

    # ── 1. Navigate ───────────────────────────────────────────────
    print(f"[threads_worker] navigating to @{username}", file=sys.stderr)
    await page.goto(
        f"https://www.threads.com/@{username}",
        wait_until="domcontentloaded",
        timeout=NAV_TIMEOUT,
    )
    await _wu.wait_for_anti_bot_clear(page, platform="threads")

    # ── 2. Wait for page to settle ────────────────────────────────
    print("[threads_worker] waiting for page to settle…", file=sys.stderr)
    _settle_js = r"""(un) => {
                const username = String(un || "").replace(/^@/, "");
                const href = window.location.href || "";
                if (href.includes("/login")) return true;
                if (document.querySelector("h1")) return true;
                if (document.querySelector("header")) return true;
                if (document.querySelector('[role="main"]')) return true;
                // Пустой / новый профиль: часто нет h1, но уже есть ссылки на followers/threads
                if (username) {
                    const fl = document.querySelector('a[href="/@' + username + '/followers"]') ||
                        document.querySelector('a[href*="/' + username + '/followers"]');
                    const tl = document.querySelector('a[href="/@' + username + '/threads"]') ||
                        document.querySelector('a[href*="/' + username + '/threads"]');
                    if (fl || tl) return true;
                }
                if (document.querySelector('meta[name="description"]')) return true;
                if (document.querySelector('meta[property="og:title"]')) return true;
                return false;
            }"""
    try:
        await page.wait_for_function(_settle_js, username, timeout=55_000)
    except Exception:
        try:
            loc = (page.url or "").lower()
        except Exception:
            loc = ""
        u_key = username.lstrip("@").lower()
        if "/login" in loc or ("/accounts/login" in loc and "threads" in loc):
            return {
                "error": (
                    "Требуется вход в Threads — откройте «Войти в Threads» в настройках "
                    "и повторите обновление."
                ),
            }
        on_threads = "threads.com" in loc or "threads.net" in loc
        profile_hint = (
            on_threads
            and u_key
            and (f"/@{u_key}" in loc or f"/@{username.lstrip('@')}" in loc)
        )
        if profile_hint:
            print(
                "[threads_worker] settle wait timed out, URL looks like profile — "
                "continuing (empty stats allowed)",
                file=sys.stderr,
            )
            settle_relaxed = True
        else:
            return {"error": "Threads не загрузился — проверь подключение."}

    # Extra time for JS to render
    await page.wait_for_timeout(2500)

    try:
        body_for_gone = await page.evaluate(
            "() => (document.body && document.body.innerText) "
            "? document.body.innerText.slice(0, 16000) : ''"
        )
    except Exception:
        body_for_gone = ""
    if _threads_body_indicates_profile_removed(body_for_gone or ""):
        return {
            "error": (
                f"{PROFILE_UNAVAILABLE_MARK}Threads @{username}: "
                "профиль удалён или недоступен на Threads."
            ),
        }

    # Debug: show page text to help diagnose selector issues
    try:
        dbg = await page.evaluate("() => document.body.innerText.slice(0, 500)")
        print(f"[threads_worker] page preview: {dbg[:300]!r}", file=sys.stderr)
    except Exception:
        pass

    # ── 3. Check login ────────────────────────────────────────────
    try:
        logged_in = await page.evaluate(_LOGGED_IN_JS)
    except Exception:
        logged_in = False
    print(f"[threads_worker] logged_in={logged_in}", file=sys.stderr)

    # ── 4. Extract profile stats ──────────────────────────────────
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

                        // ── Bio + Post count from meta description ─────────────────
                        // The Threads meta description typically looks like one of:
                        //   "Bio text · 2.3K Threads · 42.3K Followers"
                        //   "2.3K Threads, 42.3K Followers"
                        //   "2.3K Threads · 42.3K Followers - See Charlotte Clymer..."
                        // We extract postCount from it, then strip the stats from bio.
                        let postCount = '';
                        let bio = '';
                        const metaDesc = document.querySelector('meta[name="description"]');
                        if (metaDesc) {
                            const raw = metaDesc.getAttribute('content') || '';
                            // Extract post count: "N Threads" anywhere in the string
                            const pcMeta = raw.match(
                                /(\\d[\\d,.]*[KkMmBb]?)\\s*threads?/i
                            );
                            if (pcMeta) postCount = pcMeta[1];
                            // Clean bio: strip all stat tokens and trailing boilerplate.
                            // Handles separators: · • , - – and plain whitespace
                            bio = raw
                                .replace(/\\d[\\d,.]*[KkMmBb]?\\s*threads?/gi, '')
                                .replace(/\\d[\\d,.]*[KkMmBb]?\\s*(?:followers?|подписчик\\w*)/gi, '')
                                .replace(/\\s*[-–·•,]\\s*/g, ' ')
                                .replace(/\\s*-\\s*See .*$/i, '')
                                .replace(/\\s+/g, ' ')
                                .trim();
                        }

                        // ── Post count fallbacks ────────────────────────────────────
                        // Strategy 1: direct link /@username/threads in DOM
                        if (!postCount) {
                            const threadsLink =
                                document.querySelector(`a[href="/@${username}/threads"]`) ||
                                document.querySelector(`a[href*="/${username}/threads"]`);
                            if (threadsLink) {
                                const t = threadsLink.textContent.trim();
                                const m = t.match(/^(\\d[\\d,. ]*[KkMmBb]?)/);
                                if (m) postCount = m[1].replace(/[\\s,]/g, '');
                                if (!postCount) {
                                    for (const s of threadsLink.querySelectorAll('span')) {
                                        const st = (s.textContent || '').trim();
                                        if (st && /^\\d/.test(st)) { postCount = st; break; }
                                    }
                                }
                            }
                        }
                        // Strategy 2: visible page text "2.3K Threads"
                        if (!postCount) {
                            const bodyText2 = document.body.innerText || '';
                            const pcm = bodyText2.match(
                                /(\\d[\\d\\s,.]*[KkMmBb]?)\\s*(?:threads?|тредов?|публикаций)/i
                            ) || bodyText2.match(
                                /(?:threads?|тредов?|публикаций)\\s+(\\d[\\d\\s,.]*[KkMmBb]?)/i
                            );
                            if (pcm) postCount = (pcm[1] || pcm[2] || '').replace(/[\\s,]/g, '');
                        }
                        const bodyText = document.body.innerText || '';

                        // ── Avatar ─────────────────────────────────────────────────
                        // Раньше отбрасывали t51 — у Meta аватар часто именно t51.2885-19 на CDN.
                        let avatar = '';
                        const ogImg = document.querySelector('meta[property="og:image"]');
                        if (ogImg) {
                            const oc = (ogImg.getAttribute('content') || '').trim();
                            if (oc.startsWith('http')) avatar = oc;
                        }
                        const isCdnProfileish = (src) => {
                            if (!src) return false;
                            const s = src.toLowerCase();
                            return s.includes('cdninstagram') || s.includes('fbcdn.net') ||
                                s.includes('fbcdn') || s.includes('instagram.') ||
                                s.includes('scontent');
                        };
                        // Корневой layout Threads (внутреннее имя «barcelona») — аватар в шапке профиля.
                        if (!avatar) {
                            const lay = document.querySelector('#barcelona-page-layout');
                            if (lay) {
                                let best = '', bestScore = -1;
                                for (const img of lay.querySelectorAll('img[src]')) {
                                    const src = img.src || '';
                                    if (!isCdnProfileish(src)) continue;
                                    const w = img.naturalWidth || img.width || 0;
                                    const h = img.naturalHeight || img.height || 0;
                                    if (w > 720 || (w > 0 && h > 0 && w / h > 3.0)) continue;
                                    let score = 0;
                                    if (w >= 40 && w <= 360 && h >= 40 && h <= 360) score += 100;
                                    if (src.includes('t51.2885-19')) score += 40;
                                    if (score > bestScore) { bestScore = score; best = src; }
                                }
                                if (best) avatar = best;
                                if (!avatar) {
                                    for (const img of lay.querySelectorAll('img[src]')) {
                                        const src = img.src || '';
                                        if (isCdnProfileish(src)) { avatar = src; break; }
                                    }
                                }
                            }
                        }
                        if (!avatar) {
                            for (const sel of ['header img', '[role="banner"] img', 'img']) {
                                for (const img of document.querySelectorAll(sel)) {
                                    const src = img.src || '';
                                    if (!isCdnProfileish(src)) continue;
                                    avatar = src;
                                    break;
                                }
                                if (avatar) break;
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

    # ── 5–6. Посты: скролл + DOM (Threads подгружает ленту лениво; End + wheel)
    scroll_passes = 20 if logged_in else 15
    for _ in range(scroll_passes):
        await page.keyboard.press("End")
        try:
            await page.evaluate(
                "() => { window.scrollBy(0, Math.min(1400, Math.floor(innerHeight * 1.1))); }",
            )
        except Exception:
            pass
        await page.wait_for_timeout(1580)
    # Дать ответам догрузиться перед финальным merge метрик.
    await page.wait_for_timeout(2600)

    _dom_posts_js = """(username) => {
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
                                    const m = lbl.match(/([\\d][\\d\\s,.]*[KkMmBb]?)\\s*(?:views?|просмотров?|просмотр(?:ов|а)?)/i);
                                    if (m) return m[1].replace(/[\\s,]/g, '');
                                }
                                // 2. Visible text in the post: "16.4M views" / "16 464 791 views"
                                const text = el.innerText || '';
                                const m = text.match(/([\\d][\\d\\s,.]*[KkMmBb]?)\\s*(?:views?|просмотров?|просмотр(?:ов|а)?)/i);
                                if (m) return m[1].replace(/[\\s,]/g, '');
                                return '0';
                            }

                            const results = [];
                            const seen    = new Set();

                            // Each post/thread is inside an article or a pressable container
                            const containers = document.querySelectorAll(
                                'article, div[role="article"], [data-pressable-container="true"], main a[href*="/post/"]'
                            );

                            for (const el of containers) {
                                try {
                                    // Post ID from permalink (относительные и полные URL)
                                    let postId = '', postUrl = '';
                                    for (const a of el.querySelectorAll('a[href*="/post/"], a[href*="/t/"]')) {
                                        const href = a.getAttribute('href') || '';
                                        const m    = href.match(/\\/post\\/([^/?#]+)/) ||
                                                     href.match(/\\/t\\/([^/?#]+)/);
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
            }"""

    try:
        posts_raw = await page.evaluate(_dom_posts_js, username)
    except Exception as e:
        print(f"[threads_worker] DOM posts extract failed: {e}", file=sys.stderr)
        posts_raw = []
    if posts_raw:
        try:
            await page.wait_for_timeout(int(POST_VIEWS_DOM_RESCAN_MS))
        except Exception:
            pass
        try:
            posts_raw_2 = await page.evaluate(_dom_posts_js, username)
        except Exception:
            posts_raw_2 = []
        by_id = {str(p.get("id", "")): p for p in posts_raw if p.get("id")}
        for p2 in posts_raw_2 or []:
            pid = str(p2.get("id", "") or "").strip()
            if not pid or pid not in by_id:
                continue
            v1 = _parse_count(by_id[pid].get("views", "0"))
            v2 = _parse_count(p2.get("views", "0"))
            if v2 > v1:
                by_id[pid]["views"] = str(p2.get("views", "0"))

    if len(posts_raw) < 2:
        extra = await _fallback_posts_from_page_html(page, username)
        seen_ids = {str(p.get("id", "")) for p in posts_raw if p.get("id")}
        for row in extra:
            rid = str(row.get("id", ""))
            if rid and rid not in seen_ids:
                seen_ids.add(rid)
                posts_raw.append(row)

    opened_post_views = await _collect_post_views_by_opening_posts(
        page,
        username=username,
        posts_raw=posts_raw,
        network_hints=network_post_views,
    )

    # ── 7. Post-process ───────────────────────────────────────────────────────
    posts = []
    seen_post_ids: set[str] = set()
    for p in posts_raw:
        post_id = str(p.get("id", "")).strip()
        if not post_id or post_id in seen_post_ids:
            continue
        seen_post_ids.add(post_id)
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
            "view_count":    max(
                _parse_count(p.get("views", "0")),
                int(network_post_views.get(post_id, 0) or 0),
                int(opened_post_views.get(post_id, 0) or 0),
            ),
            "like_count":    _parse_count(p.get("likes", "0")),
            "comment_count": _parse_count(p.get("replies", "0")),
            "share_count":   0,
            "posted_at":     posted_at,
        })

    print(f"[threads_worker] extracted {len(posts)} posts", file=sys.stderr)

    # Если DOM «не дождались», пустой список постов не должен стирать уже сохранённые в БД.
    posts_authoritative = not (settle_relaxed and len(posts) == 0)

    return {
        "display_name":   display_name,
        "avatar_url":     avatar_url,
        "bio":            bio,
        "follower_count": follower_count,
        "like_count":     0,   # aggregated from posts in _apply_refresh
        "post_count":     post_count_val,
        "_posts":         posts,
        "_posts_authoritative": posts_authoritative,
    }


def _write_response(payload: dict) -> None:
    from platforms.worker_json_stdout import write_json_line

    try:
        write_json_line(payload)
    except Exception as exc:
        try:
            write_json_line({"error": f"Сериализация ответа worker: {exc}"})
        except Exception:
            write_json_line({"error": "Сериализация ответа worker"})


def _load_worker_utils():
    import importlib.util as _ilu

    _wu_path = Path(__file__).parent.parent / "worker_utils.py"
    if not _wu_path.exists():
        raise RuntimeError(f"worker_utils.py not found at {_wu_path}")
    _wu_spec = _ilu.spec_from_file_location("worker_utils", _wu_path)
    _wu = _ilu.module_from_spec(_wu_spec)
    _wu_spec.loader.exec_module(_wu)
    return _wu


async def _threads_recover_page(page, context):
    """После сбоя Playwright подменяем вкладку, чтобы следующий JSON-запрос не шёл в мёртвую page."""
    try:
        if page is not None and not page.is_closed():
            await page.close()
    except Exception:
        pass
    try:
        return await context.new_page()
    except Exception:
        if context.pages:
            return context.pages[0]
        return await context.new_page()


async def daemon_main() -> None:
    try:
        _wu = _load_worker_utils()
    except Exception as exc:
        _write_response({"error": str(exc)})
        return
    try:
        async with async_playwright() as pw:
            try:
                context, _browser = await _wu.launch_context(
                    pw, platform="threads", locale="en-US",
                )
            except Exception as exc:
                _write_response(
                    {"error": f"Не удалось запустить браузер Threads: {exc}"},
                )
                return
            page = context.pages[0] if context.pages else await context.new_page()
            _scrape_timeout_s = 360.0
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
                    username = str(payload.get("username", "")).lstrip("@")
                    try:
                        result = await asyncio.wait_for(
                            _run_with_page(username, page, _wu),
                            timeout=_scrape_timeout_s,
                        )
                    except (KeyboardInterrupt, SystemExit):
                        raise
                    except asyncio.TimeoutError:
                        _write_response(
                            {
                                "error": (
                                    f"Threads @{username or '?'}: превышено время ожидания "
                                    f"({int(_scrape_timeout_s)} с). Повторите обновление."
                                ),
                            },
                        )
                        page = await _threads_recover_page(page, context)
                        continue
                    except asyncio.CancelledError:
                        _write_response(
                            {
                                "error": (
                                    "Обновление Threads прервано (отмена/таймаут). "
                                    "Повторите попытку."
                                ),
                            },
                        )
                        page = await _threads_recover_page(page, context)
                        continue
                    except BaseException as exc:
                        _write_response({"error": f"Ошибка worker: {exc}"})
                        low = str(exc).lower()
                        if any(
                            x in low
                            for x in (
                                "has been closed",
                                "target page",
                                "context has been closed",
                                "browser has been closed",
                            )
                        ):
                            page = await _threads_recover_page(page, context)
                        continue
                    _write_response(result)
            finally:
                await _wu.close_context(context, _browser)
    except BaseException as exc:
        _write_response({"error": f"Критическая ошибка Threads worker: {exc}"})


if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "--daemon":
        try:
            asyncio.run(daemon_main())
        except BaseException as exc:
            try:
                from platforms.worker_json_stdout import write_json_line

                write_json_line({"error": f"Падение Threads daemon: {exc}"})
            except Exception:
                pass
            sys.exit(1)
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
