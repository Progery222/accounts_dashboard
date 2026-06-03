"""
Standalone subprocess — fetches Threads profile data via threads.net,
или список подписчиков (клик по надписи «N follower(s)» / «N подписчиков» → модалка; отдельный URL ``/followers`` не открывается).

Invoked by platforms/threads/scraper.py as:
    python threads/worker.py '{"username": "handle"}'

Payload с ``"audience_followers": true`` — см. ``accounts.audience.fetch_audience_payload``.

Uses the shared persistent Chrome profile. Requires an active Threads session
(log in once via Settings → «Войти в Threads»).

Public profiles (without auth) expose name/bio/followers — the worker works
in degraded mode if not logged in (no posts). Full post data requires auth.
"""
import asyncio
import json
import os
import random
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from playwright.async_api import async_playwright

from platforms.profile_unavailable import PROFILE_UNAVAILABLE_MARK


def threads_nav_timeout_ms() -> int:
    """Таймаут page.goto на профиль Threads (мс). По умолчанию 60 с, как в audience_scrape."""
    raw = os.getenv("THREADS_NAV_TIMEOUT_MS")
    if raw is None or not str(raw).strip():
        return 60_000
    try:
        return max(15_000, min(120_000, int(str(raw).strip())))
    except ValueError:
        return 60_000


NAV_TIMEOUT = threads_nav_timeout_ms()
LOAD_TIMEOUT = 20_000   # ms
POST_OPEN_TIMEOUT_MS = int(os.getenv("THREADS_POST_OPEN_TIMEOUT_MS", "28000") or "28000")
POST_VIEWS_MAX_POSTS = int(os.getenv("THREADS_POST_VIEWS_MAX_POSTS", "28") or "28")
POST_DELAY_MS = int(os.getenv("THREADS_POST_DELAY_MS", "1450") or "1450")
POST_RETRY_CLICKS = int(os.getenv("THREADS_POST_RETRY_CLICKS", "4") or "4")
POST_VIEWS_DOM_RESCAN_MS = int(os.getenv("THREADS_POST_VIEWS_DOM_RESCAN_MS", "2400") or "2400")
HUMAN_BATCH_SIZE = int(os.getenv("THREADS_HUMAN_BATCH_SIZE", "4") or "4")
HUMAN_BATCH_MAX_ROUNDS = int(os.getenv("THREADS_HUMAN_BATCH_MAX_ROUNDS", "18") or "18")
HUMAN_SCROLL_PAUSE_MS = int(os.getenv("THREADS_HUMAN_SCROLL_PAUSE_MS", "2100") or "2100")
HUMAN_IDLE_ROUNDS_STOP = int(os.getenv("THREADS_HUMAN_IDLE_ROUNDS_STOP", "3") or "3")


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
    skip_post_ids: set[str] | None = None,
) -> dict[str, int]:
    """
    fallback: открываем страницы постов с паузой и ретраем «Повторить попытку».
    Нужно, когда в ленте нет просмотров, либо JSON из сети даёт больше, чем DOM ленты.
    """
    out: dict[str, int] = {}
    if not posts_raw:
        return out
    hints = network_hints or {}
    already_opened = {str(x).strip() for x in (skip_post_ids or set()) if str(x).strip()}

    candidates: list[tuple[str, str]] = []
    seen: set[str] = set()
    for p in posts_raw:
        pid = str(p.get("id") or "").strip()
        if not pid or pid in seen:
            continue
        seen.add(pid)
        if pid in already_opened:
            print(
                f"[threads_worker] SKIP already opened {pid} (fallback)",
                file=sys.stderr,
            )
            continue
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


_DOM_POSTS_JS = r"""(username) => {
                            function getCount(el) {
                                if (!el) return '0';
                                const label = el.getAttribute('aria-label') || '';
                                const mL = label.match(/^([\d][\d\s,.]*)/);
                                if (mL) return mL[1].replace(/\s/g, '');
                                for (const s of [...el.querySelectorAll('span')].reverse()) {
                                    const t = (s.textContent || '').trim();
                                    if (t && /^[\d,.]+[KkMmBb]?$/.test(t)) return t;
                                }
                                return '0';
                            }

                            function getViews(el) {
                                for (const node of el.querySelectorAll('[aria-label]')) {
                                    const lbl = node.getAttribute('aria-label') || '';
                                    const m = lbl.match(/([\d][\d\s,.]*[KkMmBb]?)\s*(?:views?|просмотров?|просмотр(?:ов|а)?)/i);
                                    if (m) return m[1].replace(/[\s,]/g, '');
                                }
                                const text = el.innerText || '';
                                const m = text.match(/([\d][\d\s,.]*[KkMmBb]?)\s*(?:views?|просмотров?|просмотр(?:ов|а)?)/i);
                                if (m) return m[1].replace(/[\s,]/g, '');
                                return '0';
                            }

                            const results = [];
                            const seen    = new Set();
                            const containers = document.querySelectorAll(
                                'article, div[role="article"], [data-pressable-container="true"], main a[href*="/post/"]'
                            );

                            for (const el of containers) {
                                try {
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

                                    const textSpans = el.querySelectorAll('span[dir="auto"]');
                                    let text = '';
                                    for (const s of textSpans) {
                                        const t = (s.innerText || '').trim();
                                        if (t.length > text.length) text = t;
                                    }
                                    text = text.slice(0, 500);

                                    let ts = '';
                                    const timeEl = el.querySelector('time');
                                    if (timeEl) ts = timeEl.getAttribute('datetime') || '';

                                    let thumb = '';
                                    for (const img of el.querySelectorAll('img')) {
                                        const src = img.src || '';
                                        if (src.includes('/t51.') || src.includes('pbs.twimg')) {
                                            thumb = src; break;
                                        }
                                    }

                                    let likes = '0';
                                    for (const btn of el.querySelectorAll('button, [role="button"]')) {
                                        const svgPath = (btn.innerHTML || '');
                                        if (/M12.*heart|M8.*24|M12.*L8/i.test(svgPath) ||
                                            (btn.getAttribute('aria-label') || '').toLowerCase().includes('like')) {
                                            likes = getCount(btn);
                                            break;
                                        }
                                    }

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


def _profile_feed_url(username: str) -> str:
    u = username.lstrip("@")
    return f"https://www.threads.com/@{u}"


async def _click_profile_threads_tab(page, username: str) -> bool:
    """Вкладка «Threads» на профиле (лента публикаций)."""
    u = username.lstrip("@")
    try:
        return bool(
            await page.evaluate(
                r"""(uname) => {
                    const u = String(uname || '').replace(/^@/, '');
                    const links = document.querySelectorAll('a[href*="/threads"]');
                    for (const a of links) {
                        const h = (a.getAttribute('href') || '');
                        if (!h.includes('/' + u + '/threads') && !h.includes('/@' + u + '/threads')) continue;
                        a.click();
                        return true;
                    }
                    const tabs = document.querySelectorAll('[role="tab"], button, a');
                    for (const el of tabs) {
                        const t = (el.innerText || el.textContent || '').trim().toLowerCase();
                        if (t === 'threads' || t === 'треды' || t === 'публикации') {
                            el.click();
                            return true;
                        }
                    }
                    return false;
                }""",
                u,
            )
        )
    except Exception:
        return False


def _merge_posts_into(by_id: dict[str, dict], rows: list[dict]) -> int:
    added = 0
    for p in rows or []:
        pid = str(p.get("id") or "").strip()
        if not pid:
            continue
        if pid not in by_id:
            by_id[pid] = dict(p)
            added += 1
        else:
            cur = by_id[pid]
            for key in ("text", "ts", "thumb", "url"):
                if not cur.get(key) and p.get(key):
                    cur[key] = p[key]
            v1 = _parse_count(cur.get("views", "0"))
            v2 = _parse_count(p.get("views", "0"))
            if v2 > v1:
                cur["views"] = str(p.get("views", "0"))
            for key in ("likes", "replies"):
                n1 = _parse_count(cur.get(key, "0"))
                n2 = _parse_count(p.get(key, "0"))
                if n2 > n1:
                    cur[key] = str(p.get(key, "0"))
    return added


async def _extract_dom_posts(page, username: str) -> list[dict]:
    try:
        return await page.evaluate(_DOM_POSTS_JS, username) or []
    except Exception as e:
        print(f"[threads_worker] DOM posts extract failed: {e}", file=sys.stderr)
        return []


def _is_on_profile_feed(url: str, username: str) -> bool:
    u = username.lstrip("@").lower()
    low = (url or "").lower().split("?")[0]
    if "/post/" in low or re.search(r"/t/[a-z0-9_-]{6,}", low):
        return False
    return f"/@{u}" in low


async def _feed_scroll_y(page) -> int:
    try:
        return int(
            await page.evaluate(
                "() => Math.round(window.scrollY || document.documentElement.scrollTop || 0)",
            )
            or 0
        )
    except Exception:
        return 0


async def _restore_feed_scroll(page, y: int) -> None:
    y = max(0, int(y or 0))
    if y <= 0:
        return
    try:
        await page.evaluate("(top) => window.scrollTo(0, top)", y)
    except Exception:
        return
    await asyncio.sleep(0.55)


async def _human_scroll_feed_step(page) -> int:
    """Небольшой скролл вниз, как при просмотре ленты. Возвращает новый scrollY."""
    delta = random.randint(360, 580)
    try:
        await page.mouse.wheel(0, delta)
    except Exception:
        try:
            await page.evaluate(
                "(d) => window.scrollBy({ top: d, behavior: 'smooth' })",
                delta,
            )
        except Exception:
            pass
    pause_s = max(1.15, (HUMAN_SCROLL_PAUSE_MS + random.randint(-280, 420)) / 1000.0)
    await asyncio.sleep(pause_s)
    return await _feed_scroll_y(page)


async def _return_to_profile_feed(
    page,
    username: str,
    *,
    scroll_y: int | None = None,
    click_threads_tab: bool = True,
) -> None:
    feed_url = _profile_feed_url(username)
    try:
        await page.goto(feed_url, wait_until="domcontentloaded", timeout=NAV_TIMEOUT)
    except Exception:
        try:
            await page.goto(
                f"https://www.threads.com/@{username.lstrip('@')}",
                wait_until="domcontentloaded",
                timeout=NAV_TIMEOUT,
            )
        except Exception:
            return
    await page.wait_for_timeout(1200)
    if click_threads_tab:
        await _click_profile_threads_tab(page, username)
        await page.wait_for_timeout(900)
    if scroll_y is not None and scroll_y > 0:
        await _restore_feed_scroll(page, scroll_y)


async def _back_to_feed_from_post(page, username: str, restore_y: int) -> None:
    """Вернуться на ленту профиля без полного перезагрузки (сохранить scroll)."""
    try:
        cur_url = page.url or ""
    except Exception:
        cur_url = ""
    if _is_on_profile_feed(cur_url, username):
        await _restore_feed_scroll(page, restore_y)
        return
    try:
        await page.go_back(wait_until="domcontentloaded", timeout=POST_OPEN_TIMEOUT_MS)
        await asyncio.sleep(0.85)
        try:
            cur_url = page.url or ""
        except Exception:
            cur_url = ""
        if _is_on_profile_feed(cur_url, username):
            await _restore_feed_scroll(page, restore_y)
            return
    except Exception:
        pass
    print(
        f"[threads_worker] go_back failed — reload feed at scrollY={restore_y}",
        file=sys.stderr,
    )
    await _return_to_profile_feed(page, username, scroll_y=restore_y)


async def _open_single_post_for_views(page, username: str, pid: str, purl: str) -> int:
    if not purl:
        purl = f"https://www.threads.com/@{username.lstrip('@')}/post/{pid}"
    try:
        await page.goto(purl, wait_until="domcontentloaded", timeout=POST_OPEN_TIMEOUT_MS)
        await asyncio.sleep(1.1)
        try:
            await page.mouse.wheel(0, random.randint(180, 320))
        except Exception:
            pass
        await asyncio.sleep(0.3)
        v = await _extract_views_on_open_post(page)
        if v <= 0:
            for _ in range(POST_RETRY_CLICKS):
                clicked = await _click_retry_on_error_page(page)
                if not clicked:
                    break
                await asyncio.sleep(1.0)
                v = await _extract_views_on_open_post(page)
                if v > 0:
                    break
        return int(v or 0)
    except Exception as exc:
        print(f"[threads_worker] open post {pid}: {exc}", file=sys.stderr)
        return 0


async def _collect_posts_human_batches(
    page,
    *,
    username: str,
    post_count_hint: int | None,
    network_hints: dict[str, int],
) -> tuple[list[dict], dict[str, int]]:
    """
    Человеческий цикл: видимые посты пачками по N → открыть каждый → мягкий скролл → следующая пачка.
    """
    by_id: dict[str, dict] = {}
    opened_views: dict[str, int] = {}
    opened_ids: set[str] = set()

    target = POST_VIEWS_MAX_POSTS
    if post_count_hint and post_count_hint > 0:
        target = min(target, max(post_count_hint, HUMAN_BATCH_SIZE))

    await _return_to_profile_feed(page, username, click_threads_tab=True)
    print("[threads_worker] profile feed loaded (initial)", file=sys.stderr)
    await page.wait_for_timeout(900)

    feed_scroll_anchor = 0
    no_new_ids_rounds = 0

    for prime_i in range(4):
        dom_prime = await _extract_dom_posts(page, username)
        _merge_posts_into(by_id, dom_prime)
        html_prime = await _fallback_posts_from_page_html(page, username)
        _merge_posts_into(by_id, html_prime)
        if by_id:
            print(
                f"[threads_worker] feed primed: {len(by_id)} post ids (step {prime_i + 1})",
                file=sys.stderr,
            )
            break
        feed_scroll_anchor = await _human_scroll_feed_step(page)

    idle_rounds = 0
    batch_size = max(1, HUMAN_BATCH_SIZE)

    for round_idx in range(1, HUMAN_BATCH_MAX_ROUNDS + 1):
        try:
            on_feed = _is_on_profile_feed(page.url or "", username)
        except Exception:
            on_feed = False
        if not on_feed:
            await _return_to_profile_feed(
                page, username, scroll_y=feed_scroll_anchor, click_threads_tab=True,
            )

        dom_rows = await _extract_dom_posts(page, username)
        added_dom = _merge_posts_into(by_id, dom_rows)
        if len(by_id) < 3:
            html_rows = await _fallback_posts_from_page_html(page, username)
            _merge_posts_into(by_id, html_rows)

        visible_order: list[str] = []
        for p in dom_rows:
            pid = str(p.get("id") or "").strip()
            if pid and pid not in opened_ids and pid not in visible_order:
                visible_order.append(pid)

        batch: list[tuple[str, str]] = []
        for pid in visible_order:
            row = by_id.get(pid) or {}
            purl = str(row.get("url") or "").strip()
            batch.append((pid, purl))
            if len(batch) >= batch_size:
                break

        if not batch:
            for pid, row in by_id.items():
                if pid in opened_ids:
                    continue
                batch.append((pid, str(row.get("url") or "").strip()))
                if len(batch) >= batch_size:
                    break

        skipped_visible = [
            str(p.get("id") or "").strip()
            for p in dom_rows
            if str(p.get("id") or "").strip() in opened_ids
        ]
        if skipped_visible:
            print(
                f"[threads_worker] SKIP already opened (visible): "
                f"{', '.join(skipped_visible[:6])}"
                f"{', …' if len(skipped_visible) > 6 else ''}",
                file=sys.stderr,
            )

        if batch:
            batch_scroll_y = await _feed_scroll_y(page)
            print(
                f"[threads_worker] human batch {round_idx}: "
                f"open {len(batch)} posts (known={len(by_id)}, opened={len(opened_ids)}, "
                f"scrollY={batch_scroll_y})",
                file=sys.stderr,
            )
            for b_idx, (pid, purl) in enumerate(batch, start=1):
                v = await _open_single_post_for_views(page, username, pid, purl)
                opened_ids.add(pid)
                if v > 0:
                    opened_views[pid] = v
                hint_v = int(network_hints.get(pid, 0) or 0)
                if hint_v > v:
                    opened_views[pid] = hint_v
                print(
                    f"[threads_worker] human batch {round_idx} "
                    f"post {b_idx}/{len(batch)} {pid}: views={opened_views.get(pid, 0)}",
                    file=sys.stderr,
                )
                await _back_to_feed_from_post(page, username, batch_scroll_y)
                batch_scroll_y = max(batch_scroll_y, await _feed_scroll_y(page))
                await asyncio.sleep(max(0.35, POST_DELAY_MS / 1000.0))
            feed_scroll_anchor = max(feed_scroll_anchor, batch_scroll_y)
            idle_rounds = 0
            no_new_ids_rounds = 0
        else:
            if len(by_id) >= target and len(opened_ids) >= len(by_id):
                idle_rounds += 1
            elif len(by_id) < target:
                idle_rounds = 0
            else:
                idle_rounds += 1
            print(
                f"[threads_worker] human batch {round_idx}: nothing to open "
                f"(known={len(by_id)}, opened={len(opened_ids)}, idle={idle_rounds})",
                file=sys.stderr,
            )

        if len(opened_ids) >= target:
            print(
                f"[threads_worker] human batches: reached target {target} opened posts",
                file=sys.stderr,
            )
            break

        count_before_scroll = len(by_id)
        scroll_steps = 3 if len(by_id) < target else 1
        for _ in range(scroll_steps):
            feed_scroll_anchor = max(
                feed_scroll_anchor,
                await _human_scroll_feed_step(page),
            )
        dom_after = await _extract_dom_posts(page, username)
        added_after = _merge_posts_into(by_id, dom_after)
        html_rows = await _fallback_posts_from_page_html(page, username)
        added_after += _merge_posts_into(by_id, html_rows)
        if added_after > 0:
            no_new_ids_rounds = 0
            print(
                f"[threads_worker] scroll +{added_after} post ids "
                f"(total={len(by_id)}, scrollY={feed_scroll_anchor}, target={target})",
                file=sys.stderr,
            )
        elif len(by_id) == count_before_scroll:
            no_new_ids_rounds += 1

        if (
            no_new_ids_rounds >= max(HUMAN_IDLE_ROUNDS_STOP, 4)
            and len(opened_ids) >= len(by_id)
            and len(by_id) > 0
        ):
            print(
                f"[threads_worker] human batches: no new ids after "
                f"{no_new_ids_rounds} scroll rounds",
                file=sys.stderr,
            )
            break

        if idle_rounds >= HUMAN_IDLE_ROUNDS_STOP:
            print(
                f"[threads_worker] human batches: stop after {idle_rounds} idle rounds",
                file=sys.stderr,
            )
            break

    posts_raw = list(by_id.values())
    print(
        f"[threads_worker] human batches done: {len(posts_raw)} post ids, "
        f"{len(opened_views)} with views",
        file=sys.stderr,
    )
    return posts_raw, opened_views


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
            result = await execute_payload(page, _wu, arg)
        except (KeyboardInterrupt, SystemExit):
            raise
        except BaseException as exc:
            _write_response({"error": f"Ошибка worker: {exc}"})
            await _wu.finish_cli_session_keep_browser_by_default("threads_worker", context, _browser)
            return
        _write_response(result)
        await _wu.finish_cli_session_keep_browser_by_default("threads_worker", context, _browser)


async def execute_payload(page, _wu, arg: dict) -> dict:
    if bool(arg.get("audience_followers")):
        from platforms.threads.audience_scrape import scrape_threads_audience_followers

        u = (arg.get("username") or "").lstrip("@").strip()
        lim = int(arg.get("limit") or 100)
        _mpp = arg.get("max_posts_per_follower")
        mpp = int(_mpp) if _mpp is not None else 0
        if not u:
            return {"error": "Не указан username для съёма подписчиков."}
        _raw_aid = arg.get("audience_account_id")
        audience_account_id = int(_raw_aid) if _raw_aid is not None else None
        return await scrape_threads_audience_followers(
            page,
            _wu,
            u,
            lim,
            max_posts_per_follower=mpp,
            skip_existing_member_profiles=bool(arg.get("skip_existing_member_profiles")),
            audience_account_id=audience_account_id,
            list_only=bool(arg.get("list_only")),
            enrich_only=bool(arg.get("enrich_only")),
            enrich_usernames=arg.get("enrich_usernames"),
        )
    username = str(arg.get("username", "")).lstrip("@")
    if not username:
        return {"error": "Не указан username."}
    return await _run_with_page(username, page, _wu)


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

    # ── 5–6. Посты: пачками по N — открыть каждый, мягкий скролл, следующая пачка
    posts_raw, opened_post_views = await _collect_posts_human_batches(
        page,
        username=username,
        post_count_hint=post_count_val,
        network_hints=network_post_views,
    )

    for p in posts_raw:
        pid = str(p.get("id") or "").strip()
        ov = int(opened_post_views.get(pid, 0) or 0)
        if ov > _parse_count(p.get("views", "0")):
            p["views"] = str(ov)

    # Дозаполнить просмотры для постов, которые нашли в HTML/сети, но не успели открыть
    if posts_raw:
        extra_views = await _collect_post_views_by_opening_posts(
            page,
            username=username,
            posts_raw=posts_raw,
            network_hints=network_post_views,
            skip_post_ids=set(opened_post_views.keys()),
        )
        for pid, v in (extra_views or {}).items():
            if int(v or 0) > int(opened_post_views.get(pid, 0) or 0):
                opened_post_views[pid] = int(v)

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
    # Закрыть остальные вкладки контекста — иначе при каждом recover накапливаются окна Chromium.
    try:
        for p in list(context.pages):
            try:
                if not p.is_closed():
                    await p.close()
            except Exception:
                pass
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
            await _wu.warm_playwright_page_home(page, "threads")
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
                            execute_payload(page, _wu, payload),
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
                if _wu.worker_autoclose_browser_on_daemon_exit():
                    await _wu.close_context(context, _browser)
                else:
                    await _wu.daemon_idle_keep_browser_open("threads_worker", page, platform="threads")
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
        asyncio.run(run_once(one_payload))
