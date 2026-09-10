"""
Standalone subprocess — вызывается из platforms/instagram/scraper.py через worker_pool
(`python worker.py --daemon`, один Chromium на процесс; запросы по stdin/stdout JSON).

Ориентиры по времени на один профиль (Reels): goto до 45 с, антибот до ~120 с при
челлендже, пауза ~3.2 с, скролл 16×650 мс + финальная пауза; между профилями в батче пауза 3–5 с.

CLI для отладки: `python worker.py '{"username":"u","reels_views_only":true}'` — JSON в stdout,
затем по умолчанию Chromium не закрывается (``WORKER_AUTOCLOSE_BROWSER_ON_EXIT``).
"""
import asyncio
import json
import random
import re
import sys
from pathlib import Path

from platforms.browser_engine import async_playwright

from platforms.instagram.posts_meta import annotate_instagram_posts_payload, instagram_max_posts
from platforms.instagram.posts_meta import instagram_reels_scroll_iterations as _reels_scroll_iters
from platforms.instagram.posts_meta import instagram_reels_target_tiles as _reels_target_tiles


def _merge_posts_with_reels_grid(posts: list[dict], rows: list[dict]) -> list[dict]:
    """
    Объединяет посты с главной (timeline) и карточки только с /reels/.
    Просмотры: max(JSON главной, сетка) — нули из сетки при сбое DOM не затирают video_view_count.
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
            tv = int(p.get("view_count") or 0)
            gv = int(g.get("view_count") or 0)
            p["view_count"] = max(tv, gv)
            # Лайки и комментарии есть только у сетки (сняты наведением) —
            # берём большее, чтобы ноль с одной стороны не затёр число с другой.
            p["like_count"] = max(int(p.get("like_count") or 0), int(g.get("like_count") or 0))
            p["comment_count"] = max(int(p.get("comment_count") or 0), int(g.get("comment_count") or 0))
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
            "like_count": int(r.get("like_count") or 0),
            "comment_count": int(r.get("comment_count") or 0),
            "share_count": 0,
            "posted_at": None,
        })
    return out


# Posts metadata from profile HTML JSON; view counts are merged from /reels/ DOM below.
_EXTRACT_TIMELINE_POSTS_JS = r"""
(() => {
    const results = [];
    const pushNode = (n) => {
        if (!n || !n.shortcode) return;
        const thumb = n.thumbnail_src || n.display_url || '';
        const likes = n.edge_liked_by?.count || n.edge_media_preview_like?.count || 0;
        const comments = n.edge_media_to_comment?.count || 0;
        const views = n.video_view_count || n.video_play_count || n.play_count || 0;
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
    };

    const walk = (obj, depth = 0) => {
        if (!obj || depth > 8) return;
        if (Array.isArray(obj)) {
            for (const item of obj) walk(item, depth + 1);
            return;
        }
        if (typeof obj !== 'object') return;
        if (obj.shortcode && (obj.edge_liked_by || obj.edge_media_preview_like || obj.display_url)) {
            pushNode(obj);
        }
        for (const v of Object.values(obj)) {
            if (v && typeof v === 'object') walk(v, depth + 1);
        }
    };

    try {
        const scripts = document.querySelectorAll('script[type="application/json"]');
        for (const s of scripts) {
            try {
                const data = JSON.parse(s.textContent);
                walk(data);
            } catch(e) {}
        }

        // Deduplicate by shortcode while preserving first non-empty like/comment values.
        if (results.length > 0) {
            const byId = new Map();
            for (const r of results) {
                const prev = byId.get(r.external_id);
                if (!prev) {
                    byId.set(r.external_id, r);
                    continue;
                }
                if (!prev.like_count && r.like_count) prev.like_count = r.like_count;
                if (!prev.comment_count && r.comment_count) prev.comment_count = r.comment_count;
                if (!prev.description && r.description) prev.description = r.description;
                if (!prev.thumbnail_url && r.thumbnail_url) prev.thumbnail_url = r.thumbnail_url;
            }
            return Array.from(byId.values()).slice(0, __IG_MAX_POSTS__);
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
    return results.slice(0, __IG_MAX_POSTS__);
})()
"""

# Подставляется при загрузке модуля (см. _timeline_posts_js).
_EXTRACT_TIMELINE_POSTS_JS = _EXTRACT_TIMELINE_POSTS_JS.replace(
    "__IG_MAX_POSTS__",
    str(instagram_max_posts()),
)

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


def _parse_compact_int(raw: str) -> int:
    """«2,935», «1.1M», «83,2 тыс.» → число."""
    s = str(raw or "").strip().replace("\u00a0", "").replace("\u202f", "").replace(" ", "")
    m = re.match(r"^([\d.,]+)([KMBkmb])?$", s)
    if not m:
        digits = re.sub(r"[^\d]", "", s)
        return int(digits) if digits else 0
    num, suf = m.group(1), (m.group(2) or "").lower()
    if suf:
        num = num.replace(",", ".")
        try:
            val = float(num)
        except ValueError:
            return 0
        mul = {"k": 1e3, "m": 1e6, "b": 1e9}[suf]
        return int(round(val * mul))
    digits = re.sub(r"[^\d]", "", num)
    return int(digits) if digits else 0


async def _hover_grid_engagement(page, limit: int = 60, known: set | None = None) -> dict:
    """Лайки и комментарии с сетки — они появляются в плитке при наведении.

    Без курсора плитка показывает только просмотры («1.1M»), при наведении —
    два числа: лайки и комментарии («2,935\\n70»). Открывать каждый пост ради
    этого не нужно — сетевых запросов наведение не делает вообще.

    Если после наведения число всё ещё одно — накладка не появилась, и мы
    пропускаем плитку: иначе приняли бы просмотры за лайки.
    """
    out: dict[str, dict] = {}
    try:
        tiles = await page.query_selector_all('a[href*="/reel/"], a[href*="/p/"]')
    except Exception:
        return out
    for tile in tiles[:limit]:
        try:
            href = await tile.get_attribute("href") or ""
            m = re.search(r"/(?:reel|p)/([^/?#]+)", href)
            if not m:
                continue
            shortcode = m.group(1)
            if shortcode in out or (known and shortcode in known):
                continue
            await tile.scroll_into_view_if_needed(timeout=3000)
            await tile.hover(timeout=3000)
            await page.wait_for_timeout(180)
            text = (await tile.inner_text()) or ""
        except Exception:
            continue
        parts = [x.strip() for x in text.split("\n") if x.strip()]
        if len(parts) < 2:
            continue
        likes = _parse_compact_int(parts[0])
        comments = _parse_compact_int(parts[1])
        if likes or comments:
            out[shortcode] = {"like_count": likes, "comment_count": comments}
    return out


async def _scrape_reels_tab_once(page, _wu, username: str, post_count: int = 0) -> list:
    """Одна вкладка /reels/ для username; возвращает rows для _EXTRACT_REELS_GRID_ROWS_JS.

    ``post_count`` — сколько публикаций заявлено в профиле: от него зависит
    глубина прокрутки.
    """
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

    await page.wait_for_timeout(3200)

    if "accounts/login" in page.url or "challenge" in page.url:
        raise ValueError(
            "Instagram требует авторизации — войдите в аккаунт в настройках и повторите."
        )

    await page.evaluate("window.scrollTo(0, 0)")
    await page.wait_for_timeout(500)
    # Глубина прокрутки зависит от числа публикаций, а не одна на всех.
    # Собирать один раз в конце нельзя: Instagram выбрасывает уехавшие плитки
    # из DOM, поэтому в конце видно только последний экран — сколько ни листай,
    # больше трёх десятков постов не набиралось. Копим на каждом шаге и сами
    # плитки, и лайки под курсором, пока они ещё на странице.
    target = _reels_target_tiles(post_count)
    iters = _reels_scroll_iters(post_count)
    by_id: dict[str, dict] = {}
    eng: dict[str, dict] = {}
    stale = 0
    for _ in range(iters):
        try:
            for r in (await page.evaluate(_EXTRACT_REELS_GRID_ROWS_JS) or []):
                sid = str(r.get("external_id") or "")
                if sid and sid not in by_id:
                    by_id[sid] = r
        except Exception:
            pass
        # Лайки и комментарии снимаем здесь же: в разметке их нет, они
        # появляются только под курсором — и только пока плитка жива.
        try:
            eng.update(await _hover_grid_engagement(page, known=set(eng)))
        except Exception as exc:
            print(f"[instagram_worker] наведение за лайками: {exc}", file=sys.stderr)
        if len(by_id) >= target:
            break
        before = len(by_id)
        await page.evaluate("window.scrollBy(0, Math.min(window.innerHeight, 900))")
        await page.wait_for_timeout(900)
        if len(by_id) <= before:
            stale += 1
            if stale >= 8:
                break
        else:
            stale = 0

    rows = list(by_id.values())
    for r in rows:
        e = eng.get(str(r.get("external_id") or ""))
        if e:
            r["like_count"] = e["like_count"]
            r["comment_count"] = e["comment_count"]
    print(
        f"[instagram_worker] @{u}: публикаций {post_count or '?'}, цель {target} плиток, "
        f"собрано {len(rows)}, с лайками {len(eng)}, скроллов до {iters}",
        file=sys.stderr,
    )
    return rows


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


async def _page_indicates_profile_unavailable(page) -> bool:
    text = (await page.evaluate("document.body?.innerText || ''") or "").lower()
    markers = (
        "sorry, this page isn't available",
        "the link you followed may be broken",
        "this page isn't available",
        "user not found",
        "страница недоступна",
        "профиль удал",
        "профиль не найден",
        "ссылка недействительна",
    )
    return any(marker in text for marker in markers)


async def _profile_counts_via_web_api(page, username: str) -> dict:
    """Счётчики из web_profile_info — того же запроса, который делает сам сайт.

    Разбор вёрстки ломается при каждой смене разметки Instagram — именно так
    подписчики и превратились в нули. Здесь числа приходят готовыми и точными,
    а не округлёнными до «1,7 млн», как в подписи на странице. Запрос идёт из
    самой страницы, поэтому куки сессии подставляются браузером сами.
    """
    try:
        return await page.evaluate(
            """
            (async (u) => {
                const out = { followers: 0, following: 0, posts: 0 };
                try {
                    const r = await fetch(
                        '/api/v1/users/web_profile_info/?username=' + encodeURIComponent(u),
                        { headers: { 'X-IG-App-ID': '936619743392459' }, credentials: 'include' },
                    );
                    if (!r.ok) return out;
                    const j = await r.json();
                    const usr = j && j.data && j.data.user;
                    if (!usr) return out;
                    out.followers = (usr.edge_followed_by && usr.edge_followed_by.count) || 0;
                    out.following = (usr.edge_follow && usr.edge_follow.count) || 0;
                    out.posts = (usr.edge_owner_to_timeline_media && usr.edge_owner_to_timeline_media.count) || 0;
                } catch (_) {}
                return out;
            })
            """,
            (username or "").lstrip("@"),
        )
    except Exception:
        return {}


async def _extract_profile_counts_from_dom(page, username: str = "") -> dict:
    # Сначала спрашиваем у самого Instagram, и только потом читаем вёрстку.
    if username:
        api = await _profile_counts_via_web_api(page, username)
        if isinstance(api, dict) and int(api.get("followers") or 0) > 0:
            return {
                "followers": int(api.get("followers") or 0),
                "following": int(api.get("following") or 0),
                "posts": int(api.get("posts") or 0),
            }
    stats = await page.evaluate("""
        (() => {
            const toInt = (raw) => {
                const s = String(raw || '').replace(/\\u00a0|\\u202f|\\s/g, '').replace(/,/g, '');
                const m = s.match(/^([\\d]+(?:\\.[\\d]+)?)([kmb])?$/i);
                if (!m) {
                    const d = s.replace(/[^\\d]/g, '');
                    return d ? parseInt(d, 10) : 0;
                }
                const n = parseFloat(m[1]);
                const suf = (m[2] || '').toLowerCase();
                const mul = suf === 'k' ? 1e3 : suf === 'm' ? 1e6 : suf === 'b' ? 1e9 : 1;
                return Math.round(n * mul);
            };
            const out = { followers: 0, following: 0, posts: 0 };
            try {
                const root = document.querySelector('header') || document;
                const readTitleNum = (sel) => {
                    const el = root.querySelector(sel);
                    if (!el) return 0;
                    const t = el.getAttribute('title') || el.textContent || '';
                    return toInt(t);
                };
                // Modern IG layout keeps counters in links with title attr.
                const followersByLink =
                    readTitleNum('a[href*="/followers"] span[title]') ||
                    readTitleNum('a[href$="/followers/"] span[title]') ||
                    readTitleNum('section a[href*="/followers"] span[title]');
                const followingByLink =
                    readTitleNum('a[href*="/following"] span[title]') ||
                    readTitleNum('a[href$="/following/"] span[title]') ||
                    readTitleNum('section a[href*="/following"] span[title]');
                if (followersByLink > 0) out.followers = followersByLink;
                if (followingByLink > 0) out.following = followingByLink;

                const items = Array.from(document.querySelectorAll('header section ul li, section ul li'));
                for (const li of items) {
                    const txt = (li.textContent || '').replace(/\\s+/g, ' ').trim();
                    if (!txt) continue;
                    const m = txt.match(/([\\d.,]+\\s*[KMBkmb]?)/);
                    const val = m ? toInt(m[1]) : 0;
                    const low = txt.toLowerCase();
                    if (!out.posts && /(posts?|публикац)/i.test(low)) out.posts = val;
                    else if (!out.followers && /(followers?|подписчик)/i.test(low)) out.followers = val;
                    else if (!out.following && /(following|подписк)/i.test(low)) out.following = val;
                }
                // Fallback for layouts where list items are absent:
                // parse nearby label + value nodes in profile header.
                if (!out.followers || !out.following || !out.posts) {
                    // Ищем по всей странице, а не внутри <header>: в нынешней разметке
                    // Instagram счётчиков в header нет, и поиск в нём давал нули, хотя в тексте
                    // страницы чёрным по белому «456K followers».
                    const text = ((root.innerText || '') + ' ' + (document.body ? document.body.innerText : ''))
                        .replace(/\\s+/g, ' ');
                    const mf = text.match(/([\\d.,]+\\s*[KMBkmb]?)\\s+followers?/i);
                    const mfo = text.match(/([\\d.,]+\\s*[KMBkmb]?)\\s+following/i);
                    const mp = text.match(/([\\d.,]+\\s*[KMBkmb]?)\\s+posts?/i);
                    if (!out.followers && mf) out.followers = toInt(mf[1]);
                    if (!out.following && mfo) out.following = toInt(mfo[1]);
                    if (!out.posts && mp) out.posts = toInt(mp[1]);
                }
            } catch (_) {}
            return out;
        })()
    """)
    if not isinstance(stats, dict):
        return {"followers": 0, "following": 0, "posts": 0}
    return {
        "followers": int(stats.get("followers") or 0),
        "following": int(stats.get("following") or 0),
        "posts": int(stats.get("posts") or 0),
    }


async def scrape_full_profile_on_page(page, _wu, username: str) -> dict:
    url = f"https://www.instagram.com/{username}/"
    # ВАЖНО: сначала открываем главную страницу профиля и собираем лайки/комменты
    # из timeline JSON. Затем идём на /reels/ только за просмотрами.
    await page.goto(url, wait_until="domcontentloaded", timeout=45_000)
    await _wu.wait_for_anti_bot_clear(page, platform="instagram")
    await page.wait_for_timeout(2500)

    if "accounts/login" in page.url or "challenge" in page.url:
        raise ValueError(
            "Instagram требует авторизации — войдите в аккаунт в настройках и повторите."
        )
    if await _page_indicates_profile_unavailable(page):
        raise ValueError("Sorry, this page isn't available.")

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
    dom_stats = await _extract_profile_counts_from_dom(page, username)
    if dom_stats:
        follower_count = int(dom_stats.get("followers") or follower_count or 0)
        following_count = int(dom_stats.get("following") or following_count or 0)
        post_count = int(dom_stats.get("posts") or post_count or 0)

    if follower_count == 0 or following_count == 0 or post_count == 0:
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
            if follower_count == 0:
                follower_count = stats.get("followers", 0)
            if following_count == 0:
                following_count = stats.get("following", 0)
            if post_count == 0:
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
        return annotate_instagram_posts_payload(
            {
                "display_name": display_name,
                "avatar_url": avatar_url,
                "bio": bio,
                "follower_count": follower_count,
                "following_count": following_count,
                "like_count": 0,
                "post_count": post_count,
                "_posts": [],
            },
        )

    reels_rows = await _scrape_reels_tab_once(page, _wu, username, post_count=post_count)
    reels_dom_stats = await _extract_profile_counts_from_dom(page, username)
    if reels_dom_stats.get("followers", 0) > 0:
        follower_count = int(reels_dom_stats["followers"])
    if reels_dom_stats.get("following", 0) > 0:
        following_count = int(reels_dom_stats["following"])
    if reels_dom_stats.get("posts", 0) > 0:
        post_count = int(reels_dom_stats["posts"])
    posts = _merge_posts_with_reels_grid(posts, reels_rows)

    return annotate_instagram_posts_payload(
        {
            "display_name": display_name,
            "avatar_url": avatar_url,
            "bio": bio,
            "follower_count": follower_count,
            "following_count": following_count,
            # У профиля Instagram нет счётчика «всего лайков», как у TikTok, поэтому
            # здесь стоял жёсткий ноль — и лайки никогда не появлялись. Складываем по
            # собранным постам: это единственный доступный источник, и число честно
            # значит «лайки на собранных постах», а не за всю историю.
            "like_count": sum(int(p.get("like_count") or 0) for p in (posts or [])),
            "post_count": post_count,
            "_posts": posts or [],
        },
    )


async def scrape_profile_counts_only_on_page(page, _wu, username: str) -> dict:
    url = f"https://www.instagram.com/{username}/reels/"
    await page.goto(url, wait_until="domcontentloaded", timeout=45_000)
    await _wu.wait_for_anti_bot_clear(page, platform="instagram")
    await page.wait_for_timeout(1800)
    stats = await _extract_profile_counts_from_dom(page, username)
    return {
        "follower_count": int(stats.get("followers") or 0),
        "following_count": int(stats.get("following") or 0),
        "post_count": int(stats.get("posts") or 0),
        "_posts": [],
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
    if bool(arg.get("counts_only")):
        u = (arg.get("username") or "").lstrip("@")
        if not u:
            raise ValueError("Не указан username")
        return await scrape_profile_counts_only_on_page(page, _wu, u)
    u = (arg.get("username") or "").lstrip("@")
    if not u:
        raise ValueError("Не указан username")
    return await scrape_full_profile_on_page(page, _wu, u)


def _write_response(payload: dict) -> None:
    from platforms.worker_json_stdout import write_json_line

    write_json_line(payload)


async def run_once_cli(arg: dict) -> None:
    _wu = _load_worker_utils()
    async with async_playwright() as pw:
        context, _browser = await _wu.launch_context(
            pw, platform="instagram", locale="en-US",
            viewport={"width": 1280, "height": 900},
        )
        page = context.pages[0] if context.pages else await context.new_page()
        try:
            result = await execute_payload(page, _wu, arg)
        except (KeyboardInterrupt, SystemExit):
            raise
        except BaseException as exc:
            _write_response({"error": f"Ошибка worker: {exc}"})
            await _wu.finish_cli_session_keep_browser_by_default("instagram_worker", context, _browser)
            return
        _write_response(result)
        await _wu.finish_cli_session_keep_browser_by_default("instagram_worker", context, _browser)


async def daemon_main() -> None:
    _wu = _load_worker_utils()
    async with async_playwright() as pw:
        context, _browser = await _wu.launch_context(
            pw, platform="instagram", locale="en-US",
            viewport={"width": 1280, "height": 900},
        )
        page = context.pages[0] if context.pages else await context.new_page()
        await _wu.warm_playwright_page_home(page, "instagram")
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
            if _wu.worker_autoclose_browser_on_daemon_exit():
                await _wu.close_context(context, _browser)
            else:
                await _wu.daemon_idle_keep_browser_open("instagram_worker", page, platform="instagram")


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
        asyncio.run(run_once_cli(_cli_arg))
