"""
Standalone subprocess — вызывается из platforms/instagram/scraper.py через worker_pool
(`python worker.py --daemon`, один Chromium на процесс; запросы по stdin/stdout JSON).

Ориентиры по времени на один профиль (Reels): goto до 45 с, антибот до ~120 с при
челлендже, пауза 2 с, скролл 14×520 мс ≈ 7.3 с; между профилями в батче пауза 3–5 с.

CLI для отладки: `python worker.py '{"username":"u","reels_views_only":true}'`.
"""
import asyncio
import json
import random
import re
import sys
from pathlib import Path

from playwright.async_api import async_playwright


def _merge_posts_with_reels_grid(posts: list[dict], rows: list[dict]) -> list[dict]:
    """
    Объединяет посты с главной (timeline) и карточки только с /reels/.
    Для shortcode из сетки Reels подставляются просмотры с вкладки, в т.ч. 0.
    Рилсы, которых нет в первой порции JSON главной, добавляются в конец.
    """
    posts = [dict(p) for p in (posts or [])]
    rows = rows or []
    by_sc_grid = {r["external_id"]: r for r in rows if r.get("external_id")}
    timeline_ids = {p.get("external_id") for p in posts if p.get("external_id")}

    out: list[dict] = []
    for p in posts:
        sid = p.get("external_id")
        if sid and sid in by_sc_grid:
            g = by_sc_grid[sid]
            p["view_count"] = int(g.get("view_count") or 0)
            if not p.get("thumbnail_url") and g.get("thumbnail_url"):
                p["thumbnail_url"] = g["thumbnail_url"]
            if not p.get("description") and g.get("description"):
                p["description"] = (g.get("description") or "")[:500]
        out.append(p)

    for r in rows:
        sc = r.get("external_id")
        if not sc or sc in timeline_ids:
            continue
        out.append({
            "external_id": sc,
            "description": (r.get("description") or "")[:500],
            "thumbnail_url": r.get("thumbnail_url") or "",
            "post_url": f"https://www.instagram.com/reel/{sc}/",
            "view_count": int(r.get("view_count") or 0),
            "like_count": 0,
            "comment_count": 0,
            "share_count": 0,
            "posted_at": None,
        })
    return out


# Posts metadata from profile HTML JSON; view counts are merged from /reels/ DOM below.
_EXTRACT_TIMELINE_POSTS_JS = r"""
(() => {
    const results = [];
    try {
        const scripts = document.querySelectorAll('script[type="application/json"]');
        for (const s of scripts) {
            try {
                const data = JSON.parse(s.textContent);
                const text = JSON.stringify(data);
                const edgeMatch = text.match(/"edge_owner_to_timeline_media":\{.*?"edges":\[(.*?)\]\}/s);
                if (edgeMatch) {
                    const nodes = JSON.parse('[' + edgeMatch[1] + ']');
                    for (const edge of nodes) {
                        const n = edge.node || edge;
                        if (!n.shortcode) continue;
                        const thumb = n.thumbnail_src || n.display_url || '';
                        const likes = n.edge_liked_by?.count || n.edge_media_preview_like?.count || 0;
                        const comments = n.edge_media_to_comment?.count || 0;
                        const views = n.video_view_count || n.video_play_count || 0;
                        const caption = n.edge_media_to_caption?.edges?.[0]?.node?.text || '';
                        results.push({
                            external_id: n.shortcode,
                            description: caption.slice(0, 500),
                            thumbnail_url: thumb,
                            post_url: 'https://www.instagram.com/p/' + n.shortcode + '/',
                            view_count: views,
                            like_count: likes,
                            comment_count: comments,
                            share_count: 0,
                            posted_at: n.taken_at_timestamp ? new Date(n.taken_at_timestamp * 1000).toISOString() : null,
                        });
                    }
                    if (results.length > 0) break;
                }
            } catch(e) {}
        }

        if (results.length === 0) {
            const links = document.querySelectorAll('a[href*="/p/"], a[href*="/reel/"]');
            const seen = new Set();
            for (const a of links) {
                const m = (a.getAttribute('href') || '').match(/\/(?:p|reel)\/([A-Za-z0-9_-]+)/);
                if (!m || seen.has(m[1])) continue;
                seen.add(m[1]);
                const img = a.querySelector('img');
                results.push({
                    external_id: m[1],
                    description: img?.alt || '',
                    thumbnail_url: img?.src || '',
                    post_url: 'https://www.instagram.com/p/' + m[1] + '/',
                    view_count: 0,
                    like_count: 0,
                    comment_count: 0,
                    share_count: 0,
                    posted_at: null,
                });
            }
        }
    } catch(e) {}
    return results;
})()
"""

# Все карточки /reel/ на вкладке Reels: shortcode, просмотры (включая 0), превью.
# Важно: не брать «первый числовой span» наугад — см. extractViewsFromCard.
_EXTRACT_REELS_GRID_ROWS_JS = r"""
(() => {
    const parseCount = (raw) => {
        if (!raw) return 0;
        let s = String(raw).replace(/\u00a0/g, ' ').trim();
        s = s.replace(/\s+/g, '').replace(',', '.').toUpperCase();
        const m = s.match(/^([\d]+(?:\.[\d]+)?)([KMB])?$/);
        if (!m) {
            const digits = s.replace(/[^\d]/g, '');
            return digits ? parseInt(digits, 10) : 0;
        }
        const num = parseFloat(m[1]);
        const mul = m[2] === 'K' ? 1_000 : m[2] === 'M' ? 1_000_000 : m[2] === 'B' ? 1_000_000_000 : 1;
        return Number.isFinite(num) ? Math.round(num * mul) : 0;
    };

    const parseLeadingNumber = (fragment) => {
        if (!fragment) return 0;
        const t = fragment.replace(/\u00a0/g, ' ').replace(/\s+/g, ' ').trim();
        const m = t.match(/^([\d\s.,]+)\s*([KMBkmb]?)/);
        if (!m) return 0;
        return parseCount(m[1].replace(/\s/g, '') + (m[2] || '').toUpperCase());
    };

    const insideLikeUi = (el) => {
        let n = el;
        for (let i = 0; i < 10 && n; i++) {
            const lab = (n.getAttribute?.('aria-label') || '').toLowerCase();
            if (!lab) {
                n = n.parentElement;
                continue;
            }
            if ((lab.includes('like') || lab.includes('лайк')) &&
                !lab.includes('view') && !lab.includes('просмотр') && !lab.includes('play')) {
                return true;
            }
            n = n.parentElement;
        }
        return false;
    };

    const extractViewsFromCard = (link) => {
        // Текущая разметка сетки Reels: счётчик на превью — div._aajz > div._aaj_ > span > span
        // (без слова "views" в innerText, поэтому regex ниже часто не срабатывал — оставался JSON).
        const overlaySpans = link.querySelectorAll('div._aajz div._aaj_ span span');
        for (const sp of overlaySpans) {
            if (!sp?.textContent || insideLikeUi(sp)) continue;
            const raw = sp.textContent.trim().replace(/\s/g, '');
            if (!/^[\d][\d.,]*[KMBkmb]?$/i.test(raw)) continue;
            const v = parseLeadingNumber(raw);
            if (v > 0) return v;
        }

        const inner = (link.innerText || '').replace(/\u00a0/g, ' ');
        const normalized = inner.replace(/\s+/g, ' ').trim();

        const viewPatterns = [
            /([\d\s.,]+)\s*[KMBkmb]?\s+views?\b/i,
            /([\d\s.,]+)\s*[KMBkmb]?\s+просмотр/i,
            /([\d\s.,]+)\s*[KMBkmb]?\s+plays?\b/i,
        ];
        for (const pat of viewPatterns) {
            const mm = normalized.match(pat);
            if (mm) return parseLeadingNumber(mm[1]);
        }

        const deepSpan = link.querySelector('div > div:nth-child(2) div div div span span');
        if (deepSpan?.textContent && !insideLikeUi(deepSpan)) {
            const chunk = (deepSpan.closest('div')?.innerText || '').replace(/\s+/g, ' ');
            if (/views?|просмотр|plays?/i.test(chunk)) {
                const v = parseCount(deepSpan.textContent.trim());
                if (v > 0) return v;
            }
        }

        const labeled = link.querySelectorAll('[aria-label]');
        for (const node of labeled) {
            const al = node.getAttribute('aria-label') || '';
            const low = al.toLowerCase();
            if ((low.includes('like') || low.includes('лайк')) &&
                !low.includes('view') && !low.includes('просмотр') && !low.includes('play')) {
                continue;
            }
            const vm = al.match(/([\d\s.,]+)\s*[KMBkmb]?\s*(views?|просмотров?|просмотр|plays?)/i);
            if (vm) return parseLeadingNumber(vm[1]);
            if (/view|просмотр|play|reel/i.test(al)) {
                const nm = al.match(/([\d\s.,]+)\s*[KMBkmb]?/);
                if (nm) return parseLeadingNumber(nm[1]);
            }
        }

        return 0;
    };

    const rows = [];
    const seen = new Set();
    // Только /reel/ на вкладке Reels — полный список карточек (включая 0 просмотров).
    for (const link of document.querySelectorAll('a[href*="/reel/"]')) {
        const href = link.getAttribute('href') || '';
        const m = href.match(/\/reel\/([A-Za-z0-9_-]+)/);
        if (!m) continue;
        const shortcode = m[1];
        if (seen.has(shortcode)) continue;
        seen.add(shortcode);
        const img = link.querySelector('img');
        rows.push({
            external_id: shortcode,
            view_count: extractViewsFromCard(link),
            thumbnail_url: img?.src || '',
            description: (img?.alt || '').slice(0, 500),
        });
    }
    return rows;
})()
"""


async def _scrape_reels_tab_once(page, _wu, username: str) -> list:
    """Одна вкладка /reels/ для username; возвращает rows для _EXTRACT_REELS_GRID_ROWS_JS."""
    u = username.lstrip("@")
    reels_url = f"https://www.instagram.com/{u}/reels/"
    try:
        await page.goto(reels_url, wait_until="domcontentloaded", timeout=45_000)
    except Exception as exc:
        print(
            f"[instagram_worker] /reels/ не открылась для @{u} (пропуск сетки): {exc}",
            file=sys.stderr,
        )
        return []

    try:
        await _wu.wait_for_anti_bot_clear(page, platform="instagram")
    except ValueError:
        raise
    except Exception as exc:
        print(f"[instagram_worker] anti-bot на /reels/ @{u}: {exc}", file=sys.stderr)
        return []

    await page.wait_for_timeout(2000)

    if "accounts/login" in page.url or "challenge" in page.url:
        raise ValueError(
            "Instagram требует авторизации — войдите в аккаунт в настройках и повторите."
        )

    await page.evaluate("window.scrollTo(0, 0)")
    await page.wait_for_timeout(400)
    for _ in range(14):
        await page.evaluate("window.scrollBy(0, Math.min(window.innerHeight, 900))")
        await page.wait_for_timeout(520)

    return await page.evaluate(_EXTRACT_REELS_GRID_ROWS_JS) or []


def _load_worker_utils():
    import importlib.util as _ilu

    _wu_path = Path(__file__).parent.parent / "worker_utils.py"
    if not _wu_path.exists():
        print(
            f"[instagram_worker] ERROR: worker_utils.py not found at {_wu_path}",
            file=sys.stderr,
        )
        raise RuntimeError("worker_utils.py не найден")
    _wu_spec = _ilu.spec_from_file_location("worker_utils", _wu_path)
    _wu = _ilu.module_from_spec(_wu_spec)
    _wu_spec.loader.exec_module(_wu)
    return _wu


async def scrape_reels_batch_on_page(page, _wu, usernames: list[str]) -> dict:
    """Несколько профилей на одной странице: пауза 3–5 с между переходами."""
    grids: dict[str, list] = {}
    for i, raw in enumerate(usernames):
        u = raw.lstrip("@")
        if i > 0:
            await asyncio.sleep(random.uniform(3.0, 5.0))
        rows = await _scrape_reels_tab_once(page, _wu, u)
        grids[u.lower()] = rows
    return {"_batch_reels_grids": grids}


async def scrape_reels_only_single(page, _wu, username: str) -> dict:
    rows = await _scrape_reels_tab_once(page, _wu, username)
    reels_views = {
        str(r["external_id"]): int(r.get("view_count") or 0) for r in rows
    }
    return {
        "_reels_views": reels_views,
        "_reels_grid": rows,
        "_posts": [],
    }


async def scrape_full_profile_on_page(page, _wu, username: str) -> dict:
    url = f"https://www.instagram.com/{username}/"
    await page.goto(url, wait_until="domcontentloaded", timeout=45_000)
    await _wu.wait_for_anti_bot_clear(page, platform="instagram")
    await page.wait_for_timeout(2500)

    if "accounts/login" in page.url or "challenge" in page.url:
        raise ValueError(
            "Instagram требует авторизации — войдите в аккаунт в настройках и повторите."
        )

    desc = await page.evaluate(
        "document.querySelector('meta[name=\"description\"]')?.content || ''"
    )
    follower_count = 0
    following_count = 0
    post_count = 0

    m = re.search(
        r'([\d,\.]+[KkMmBb]?)\s+Followers?,\s+([\d,\.]+[KkMmBb]?)\s+Following,\s+([\d,\.]+[KkMmBb]?)\s+Posts?',
        desc, re.I,
    )
    if m:
        follower_count = _parse(m.group(1))
        following_count = _parse(m.group(2))
        post_count = _parse(m.group(3))
    else:
        stats = await page.evaluate("""
            (() => {
                try {
                    const text = document.documentElement.innerHTML;
                    let m = text.match(/"edge_followed_by":\\{"count":(\\d+)\\}/);
                    const followers = m ? parseInt(m[1]) : 0;
                    m = text.match(/"edge_follow":\\{"count":(\\d+)\\}/);
                    const following = m ? parseInt(m[1]) : 0;
                    m = text.match(/"edge_owner_to_timeline_media":\\{"count":(\\d+)\\}/);
                    const posts = m ? parseInt(m[1]) : 0;
                    return {followers, following, posts};
                } catch(e) { return null; }
            })()
        """)
        if stats:
            follower_count = stats.get("followers", 0)
            following_count = stats.get("following", 0)
            post_count = stats.get("posts", 0)

    display_name = await page.evaluate(
        "document.querySelector('meta[property=\"og:title\"]')?.content?.split('•')[0]?.trim() || ''"
    ) or username

    avatar_url = await page.evaluate(
        "document.querySelector('meta[property=\"og:image\"]')?.content || ''"
    )

    bio = await page.evaluate("""
        (() => {
            const el = document.querySelector('meta[name="description"]');
            if (!el) return '';
            const c = el.content || '';
            const idx = c.indexOf(' - See Instagram');
            return idx > -1 ? '' : c;
        })()
    """)

    posts = await page.evaluate(_EXTRACT_TIMELINE_POSTS_JS) or []

    # У аккаунтов без постов и рилсов /reels/ часто редирект или пустой DOM — не ходим туда,
    # иначе лишние goto, антибот и риск «зависания» без строки в stdout.
    if post_count == 0 and len(posts) == 0:
        return {
            "display_name": display_name,
            "avatar_url": avatar_url,
            "bio": bio,
            "follower_count": follower_count,
            "following_count": following_count,
            "like_count": 0,
            "post_count": post_count,
            "_posts": [],
        }

    reels_rows = await _scrape_reels_tab_once(page, _wu, username)
    posts = _merge_posts_with_reels_grid(posts, reels_rows)

    return {
        "display_name": display_name,
        "avatar_url": avatar_url,
        "bio": bio,
        "follower_count": follower_count,
        "following_count": following_count,
        "like_count": 0,
        "post_count": post_count,
        "_posts": posts or [],
    }


async def execute_payload(page, _wu, arg: dict) -> dict:
    usernames_batch = arg.get("usernames")
    reels_views_only = bool(arg.get("reels_views_only"))
    if (
        isinstance(usernames_batch, list)
        and len(usernames_batch) > 1
        and reels_views_only
    ):
        return await scrape_reels_batch_on_page(page, _wu, usernames_batch)
    if reels_views_only:
        u = (arg.get("username") or "").lstrip("@")
        if not u:
            raise ValueError("Не указан username")
        return await scrape_reels_only_single(page, _wu, u)
    u = (arg.get("username") or "").lstrip("@")
    if not u:
        raise ValueError("Не указан username")
    return await scrape_full_profile_on_page(page, _wu, u)


def _write_response(payload: dict) -> None:
    from platforms.worker_json_stdout import write_json_line

    write_json_line(payload)


async def run_once_cli(arg: dict) -> dict:
    _wu = _load_worker_utils()
    async with async_playwright() as pw:
        context, _browser = await _wu.launch_context(
            pw, platform="instagram", locale="en-US",
            viewport={"width": 1280, "height": 900},
        )
        page = context.pages[0] if context.pages else await context.new_page()
        try:
            return await execute_payload(page, _wu, arg)
        finally:
            await _wu.close_context(context, _browser)


async def daemon_main() -> None:
    _wu = _load_worker_utils()
    async with async_playwright() as pw:
        context, _browser = await _wu.launch_context(
            pw, platform="instagram", locale="en-US",
            viewport={"width": 1280, "height": 900},
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
                    result = await execute_payload(page, _wu, payload)
                except (KeyboardInterrupt, SystemExit):
                    raise
                except asyncio.CancelledError:
                    _write_response(
                        {
                            "error": (
                                "Обновление Instagram прервано (отмена/таймаут). "
                                "Повторите попытку."
                            ),
                        },
                    )
                    continue
                except ValueError as exc:
                    _write_response({"error": str(exc)})
                    continue
                except BaseException as exc:
                    _write_response({"error": f"Ошибка worker: {exc}"})
                    continue
                _write_response(result)
        finally:
            await _wu.close_context(context, _browser)


def _parse(text: str) -> int:
    text = text.strip().replace(',', '')
    m = re.match(r'^([\d]+(?:\.[\d]+)?)\s*([KkMmBb]?)', text.upper())
    if not m:
        return 0
    num = float(m.group(1))
    suffix = m.group(2)
    return int(num * {'K': 1_000, 'M': 1_000_000, 'B': 1_000_000_000}.get(suffix, 1))


if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "--daemon":
        asyncio.run(daemon_main())
    else:
        if len(sys.argv) < 2:
            _write_response({"error": "Отсутствует payload"})
            sys.exit(1)
        try:
            _cli_arg = json.loads(sys.argv[1])
        except Exception:
            _write_response({"error": "Невалидный JSON payload"})
            sys.exit(1)
        _write_response(asyncio.run(run_once_cli(_cli_arg)))
