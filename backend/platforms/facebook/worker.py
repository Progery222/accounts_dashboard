"""
Standalone subprocess — fetches Facebook Page / profile data.
Invoked by platforms/facebook/scraper.py as:
    python facebook/worker.py '{"username": "pagename"}'

Uses the shared persistent Chrome profile (force_persistent=True).
Runs headless=False with the window placed off-screen.

Публичный скрапинг без обязательного входа: при «стене» логина всё равно
пытаемся вытащить og:title / main — раньше жёстко падали на ложном auth.
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

NAV_TIMEOUT         = 35_000
LOAD_TIMEOUT        = 25_000
AUTH_DETECT_TIMEOUT = 12_000
MAX_POSTS           = int(os.getenv("FACEBOOK_MAX_POSTS", "12") or "12")
PAUSE_PRE_NAV_MIN_MS = int(os.getenv("FACEBOOK_PAUSE_PRE_NAV_MIN_MS", "700") or "700")
PAUSE_PRE_NAV_MAX_MS = int(os.getenv("FACEBOOK_PAUSE_PRE_NAV_MAX_MS", "1700") or "1700")
PAUSE_SCROLL_MIN_MS = int(os.getenv("FACEBOOK_PAUSE_SCROLL_MIN_MS", "900") or "900")
PAUSE_SCROLL_MAX_MS = int(os.getenv("FACEBOOK_PAUSE_SCROLL_MAX_MS", "1900") or "1900")
PAUSE_PRE_M_BASIC_MIN_MS = int(os.getenv("FACEBOOK_PAUSE_PRE_MBASIC_MIN_MS", "800") or "800")
PAUSE_PRE_M_BASIC_MAX_MS = int(os.getenv("FACEBOOK_PAUSE_PRE_MBASIC_MAX_MS", "1800") or "1800")
PAUSE_BETWEEN_TASKS_MIN_MS = int(os.getenv("FACEBOOK_PAUSE_BETWEEN_TASKS_MIN_MS", "1000") or "1000")
PAUSE_BETWEEN_TASKS_MAX_MS = int(os.getenv("FACEBOOK_PAUSE_BETWEEN_TASKS_MAX_MS", "2200") or "2200")


def _ms_jitter(min_ms: int, max_ms: int) -> float:
    lo = max(0, min_ms)
    hi = max(lo, max_ms)
    return random.uniform(lo, hi) / 1000.0


# ── Python parse helper ───────────────────────────────────────────────────────

def _parse_count(text: str) -> int:
    """
    '15 млн', '15,4 млн', '1.2M', '88.4K', '1 234 567',
    '15 млн — Нравится', '88.4K followers'  →  int
    """
    if not text:
        return 0
    text = str(text).strip()
    # Strip label after separator or space
    text = re.split(
        r'\s*(?:—|[-–·•])\s*|\s+(?:people|person|likes?|followers?|подписч\w*|нравится)',
        text, maxsplit=1, flags=re.I,
    )[0].strip()
    # Normalise
    text = text.replace('\xa0', '').replace('\u202f', '').replace(' ', '').replace(',', '.')
    # Russian: млн/тыс/млрд
    ru = re.match(r'^([\d]+(?:\.[\d]+)?)(млрд|млн|тыс)', text, re.I)
    if ru:
        num  = float(ru.group(1))
        mult = {'млн': 1_000_000, 'тыс': 1_000, 'млрд': 1_000_000_000}[ru.group(2).lower()]
        return int(num * mult)
    # Latin K/M/B/T
    lat = re.match(r'^([\d]+(?:\.[\d]+)?)([KMBTkmbt]?)$', text)
    if lat:
        num  = float(lat.group(1))
        mult = {'K': 1_000, 'M': 1_000_000, 'B': 1_000_000_000,
                'T': 1_000_000_000_000}.get(lat.group(2).upper(), 1)
        return int(num * mult)
    digits = re.sub(r'[^\d]', '', text)
    return int(digits) if digits else 0


def _extract_post_id_from_url(url: str) -> str:
    if not url:
        return ""
    s = str(url)
    patterns = [
        r"/posts/([\w-]{5,})",
        r"story_fbid=([\w-]{5,})",
        r"/videos/([\w-]{5,})",
        r"/reel/([\w-]{5,})",
        r"/permalink/([\w-]{5,})",
    ]
    for p in patterns:
        m = re.search(p, s)
        if m:
            return m.group(1)
    return ""


def _collect_post_metrics_from_json(payload, out: dict[str, dict]) -> None:
    """Рекурсивно собирает post_id -> метрики из JSON-ответов Facebook."""
    stack = [payload]
    while stack:
        cur = stack.pop()
        if isinstance(cur, list):
            stack.extend(cur)
            continue
        if not isinstance(cur, dict):
            continue

        pid_candidates: set[str] = set()
        for key in ("id", "post_id", "story_fbid", "feedback_id"):
            val = str(cur.get(key) or "").strip()
            if re.match(r"^[\w-]{5,}$", val):
                pid_candidates.add(val)
        for key in ("permalink_url", "url", "story_url", "post_url"):
            pid = _extract_post_id_from_url(str(cur.get(key) or ""))
            if pid:
                pid_candidates.add(pid)

        metrics = {
            "reactions": 0,
            "comments": 0,
            "shares": 0,
            "views": 0,
            "post_url": "",
        }
        for key in ("reaction_count", "reactions", "like_count"):
            metrics["reactions"] = max(metrics["reactions"], _parse_count(cur.get(key)))
        for key in ("comment_count", "comments"):
            metrics["comments"] = max(metrics["comments"], _parse_count(cur.get(key)))
        for key in ("share_count", "shares"):
            metrics["shares"] = max(metrics["shares"], _parse_count(cur.get(key)))
        for key in ("view_count", "video_view_count", "video_play_count", "play_count", "views"):
            metrics["views"] = max(metrics["views"], _parse_count(cur.get(key)))
        for key in ("permalink_url", "url", "story_url", "post_url"):
            u = str(cur.get(key) or "")
            if "/facebook.com/" in u or "/fb.watch/" in u:
                metrics["post_url"] = u
                break

        if pid_candidates and any(metrics[k] > 0 for k in ("reactions", "comments", "shares", "views")):
            for pid in pid_candidates:
                prev = out.get(pid) or {}
                out[pid] = {
                    "reactions": max(int(prev.get("reactions", 0) or 0), metrics["reactions"]),
                    "comments": max(int(prev.get("comments", 0) or 0), metrics["comments"]),
                    "shares": max(int(prev.get("shares", 0) or 0), metrics["shares"]),
                    "views": max(int(prev.get("views", 0) or 0), metrics["views"]),
                    "post_url": str(prev.get("post_url") or metrics["post_url"] or ""),
                }

        for v in cur.values():
            if isinstance(v, (dict, list)):
                stack.append(v)


async def _capture_response_post_metrics(response, out: dict[str, dict]) -> None:
    try:
        url = (response.url or "").lower()
    except Exception:
        url = ""
    if not url:
        return
    if "/graphql/" not in url and "api" not in url and "facebook.com" not in url:
        return
    try:
        ctype = (response.headers or {}).get("content-type", "").lower()
    except Exception:
        ctype = ""
    if "json" not in ctype and "/graphql/" not in url:
        return
    try:
        payload = await response.json()
    except Exception:
        return
    before = len(out)
    _collect_post_metrics_from_json(payload, out)
    after = len(out)
    if after > before:
        print(f"[facebook_worker] network post metrics +{after - before} (total={after})", file=sys.stderr)


# ── Auth detection JS ─────────────────────────────────────────────────────────

_STATE_JS = """
    () => {
        const url = window.location.href;
        const path = window.location.pathname || '';
        if (url.includes('/checkpoint') || url.includes('/recover') ||
            url.includes('login_attempt')) return 'auth';
        // Только явная страница входа, а не /username с виджетом «Войти»
        if (path === '/login' || path === '/login.php' || path.startsWith('/login/'))
            return 'auth';

        const hasOgTitle = !!document.querySelector('meta[property="og:title"]');
        const hasMain = !!document.querySelector('[role="main"]');
        const hasPagelet = !!document.querySelector('[data-pagelet]');
        const hasH1 = !!document.querySelector('h1');
        if (hasOgTitle || hasMain || hasPagelet || hasH1) return 'loaded';
        if (document.querySelector('[role="navigation"]')) return 'loaded';

        // Полноэкранный логин без оболочки профиля
        if (document.querySelector('input[name="email"]') &&
            document.querySelector('input[name="pass"]')) return 'auth';
        return 'loading';
    }
"""

# ── Profile extraction JS ─────────────────────────────────────────────────────
# Single arrow-function — Playwright clearly calls it with (username).

_PROFILE_JS = """(username) => {
    // ── parseNum: handles "15 млн", "15,4 тыс", "1.2M", "88K" ──────────────
    function parseNum(t) {
        t = (t || '').toString().replace(/[\\u00a0\\u202f]/g, '').trim();
        // Russian suffix: млн / тыс / млрд
        const ru = t.match(/^([\\d]+(?:[.,][\\d]+)?)\\s*(млрд|млн|тыс)/i);
        if (ru) {
            const n = parseFloat(ru[1].replace(',', '.'));
            const m = { млн: 1e6, тыс: 1e3, млрд: 1e9 }[ru[2].toLowerCase()] || 1;
            return Math.round(n * m);
        }
        // Latin suffix
        t = t.replace(/[\\s,]/g, '').replace(',', '.');
        const la = t.match(/^([\\d]+(?:\\.[\\d]+)?)([KkMmBb]?)$/);
        if (!la) return 0;
        const mult = { K: 1e3, M: 1e6, B: 1e9 }[la[2].toUpperCase()] || 1;
        return Math.round(parseFloat(la[1]) * mult);
    }

    // ── Display name ─────────────────────────────────────────────────────────
    let displayName = '';
    const ogTitle = document.querySelector('meta[property="og:title"]');
    if (ogTitle) {
        displayName = (ogTitle.getAttribute('content') || '').trim()
            .replace(/\\s*\\|\\s*Facebook.*$/i, '')
            .replace(/\\s*[-\\u2013]\\s*Facebook.*$/i, '')
            .trim();
    }
    if (!displayName) {
        for (const h of document.querySelectorAll('[data-pagelet] h1,[role="main"] h1,h1')) {
            const t = (h.textContent || '').trim();
            if (t && t.length < 120) { displayName = t; break; }
        }
    }
    if (!displayName) {
        displayName = document.title
            .replace(/\\s*\\|\\s*Facebook.*$/i, '')
            .replace(/\\s*[-\\u2013]\\s*Facebook.*$/i, '')
            .trim();
    }

    // ── Avatar ───────────────────────────────────────────────────────────────
    let avatar = '';
    const ogImg = document.querySelector('meta[property="og:image"]');
    if (ogImg) avatar = (ogImg.getAttribute('content') || '').trim();
    if (!avatar) {
        for (const img of document.querySelectorAll('img')) {
            const src = img.src || '';
            if ((src.includes('scontent') || src.includes('fbcdn')) &&
                !src.includes('/p40x40/') && !src.includes('/p16x16/') &&
                !src.includes('/p32x32/') && !src.includes('/p48x48/')) {
                avatar = src; break;
            }
        }
    }

    // ── Page body text (most reliable stat source) ────────────────────────────
    const bodyText = document.body.innerText || '';

    // ── Likes (Нравится) ─────────────────────────────────────────────────────
    // Formats: "15 млн — Нравится", "15M likes", "N people like this"
    let pageLikes = '';
    const likeRe = [
        // Number and label on separate lines (personal profiles): 21 tys. newline нравится
        /([\\d][\\d\\u00a0 ]*)\\s*(млрд|млн|тыс)[.,]?\\nнравится/i,
        // Same without suffix: plain number then newline then нравится
        /([\\d][\\d\\u00a0 ,.]+)\\nнравится/i,
        // "число — Нравится" (с суффиксом на одной строке): "15 млн — Нравится"
        /([\\d][\\d\\s,.]*)\\s*(млрд|млн|тыс)[.,]?\\s*(?:[-\u2013\u2014]\\s*)?[\\s"«\u201c\u201e\u00ab]*нравится/i,
        // "число — Нравится" (без суффикса на одной строке): "1 234 — Нравится"
        /([\\d][\\d\\s]*)\\s*[-\u2013\u2014]\\s*[\\s"«\u201c\u201e\u00ab]*нравится/i,
        // Reversed: "Нравится страница ..." then newline then "21 тыс."
        /нравится[^\\n]{0,120}\\n([\\d][\\d\\s]*)\\s*(млрд|млн|тыс)?/i,
        // "X чел. / человек отметили (это как) понравившееся"
        /([\\d][\\d\\s,.]*)\\s*(?:млрд|млн|тыс)?[.,]?\\s*(?:чел\\.|человек)[^\\n]*понравившееся/i,
        // English
        /([\\d][\\d,.]*\\s*[KkMmBb]?)\\s*likes?[\\s\\n·•,]/i,
        /([\\d][\\d\\s,.]*)\\s*(?:people\\s+)?like\\s+this/i,
    ];
    const likeDbg = [];
    for (const re of likeRe) {
        const m = bodyText.match(re);
        likeDbg.push(re.toString().slice(0,60) + ' => ' + (m ? 'MATCH g1=' + m[1] + ' g2=' + m[2] : 'no'));
        if (m) {
            pageLikes = m[1].trim();
            // Reattach Russian suffix if captured outside group 1
            if (m[2] && !/(млн|тыс|млрд)/i.test(pageLikes))
                pageLikes += ' ' + m[2];
            break;
        }
    }

    // ── Followers (подписчиков) ───────────────────────────────────────────────
    // Formats: "15 млн — подписчиков", "15M followers", "N people follow this"
    let followers = '';
    const follRe = [
        /([\\d][\\d\\s,.]*)\\s*(млрд|млн|тыс)[.,]?\\s*(?:—\\s*)?подписчик/i,
        /([\\d][\\d,.]*\\s*[KkMmBb]?)\\s*followers?[\\s\\n·•,]/i,
        /([\\d][\\d\\s,.]*)\\s*(?:people\\s+)?follow\\s+this/i,
    ];
    for (const re of follRe) {
        const m = bodyText.match(re);
        if (m) {
            followers = m[1].trim();
            if (m[2] && !/(млн|тыс|млрд)/i.test(followers))
                followers += ' ' + m[2];
            break;
        }
    }

    // ── Bio ───────────────────────────────────────────────────────────────────
    let bio = '';
    const ogDesc = document.querySelector('meta[property="og:description"]');
    if (ogDesc) {
        bio = (ogDesc.getAttribute('content') || '').trim()
            .replace(/[\\d][\\d\\s,.]*(?:млн|тыс|млрд|[KkMmBb])?\\s*(?:—\\s*)?(?:нравится|подписчик\\w*|followers?|likes?)/gi, '')
            .replace(/\\s*[·\\-\\u2013,]\\s*/g, ' ')
            .replace(/\\s+/g, ' ')
            .trim();
    }

    // Debug: show ALL lines that contain "нравится" plus neighbouring lines
    let dbgLikes = '';
    const nravIdx = bodyText.toLowerCase().indexOf('нравится');
    if (nravIdx >= 0)
        dbgLikes = bodyText.slice(Math.max(0, nravIdx - 60), nravIdx + 60);
    const lines = bodyText.split('\\n');
    const nravLines = [];
    for (let i = 0; i < lines.length; i++) {
        if (lines[i].toLowerCase().includes('нравится')) {
            nravLines.push('L' + i + ': ' + JSON.stringify(lines.slice(Math.max(0,i-1), i+3).join('|')));
        }
    }

    return {
        displayName,
        avatar,
        bio,
        followers,
        pageLikes,
        dbg: bodyText.slice(0, 300),
        dbgLikes,
        likeDbg,
        nravLines,
    };
}"""

# ── Posts extraction JS ───────────────────────────────────────────────────────

_POSTS_JS = """(params) => {
    const username = String((params && params.username) || '');
    const maxPosts = Number((params && params.maxPosts) || 5);
    function parseNum(t) {
        t = (t || '').toString().replace(/[\\u00a0\\u202f]/g, '').trim();
        const ru = t.match(/^([\\d]+(?:[.,][\\d]+)?)\\s*(млрд|млн|тыс)/i);
        if (ru) {
            const n = parseFloat(ru[1].replace(',', '.'));
            const m = { млн: 1e6, тыс: 1e3, млрд: 1e9 }[ru[2].toLowerCase()] || 1;
            return Math.round(n * m);
        }
        t = t.replace(/[\\s,]/g, '').replace(',', '.');
        const la = t.match(/^([\\d]+(?:\\.[\\d]+)?)([KkMmBb]?)$/);
        if (!la) return 0;
        const mult = { K: 1e3, M: 1e6, B: 1e9 }[la[2].toUpperCase()] || 1;
        return Math.round(parseFloat(la[1]) * mult);
    }

    function getBtnCount(btn) {
        if (!btn) return 0;
        const lbl = btn.getAttribute('aria-label') || '';
        const mL = lbl.match(/([\\d][\\d\\s,.]*)\\s*(?:reactions?|comments?|shares?|reacts?)/i);
        if (mL) return parseNum(mL[1]);
        for (const el of [...btn.querySelectorAll('span,div')].reverse()) {
            if (el.children.length > 0) continue;
            const t = (el.textContent || '').trim();
            if (/^[\\d][\\d.,]*[KkMmBb]?$/.test(t)) return parseNum(t);
        }
        return 0;
    }

    const MAX     = Math.max(1, Number(maxPosts || 5));
    const results = [];
    const seen    = new Set();

    for (const art of document.querySelectorAll('[role="article"]')) {
        if (results.length >= MAX) break;
        try {
            let postId = '', postUrl = '';
            for (const a of art.querySelectorAll(
                'a[href*="/posts/"],a[href*="/videos/"],' +
                'a[href*="story_fbid"],a[href*="/reel/"],a[href*="/permalink/"]'
            )) {
                const href = a.getAttribute('href') || '';
                const m = href.match(/\\/posts\\/([\\w-]+)/)  ||
                          href.match(/story_fbid=([\\w-]+)/)  ||
                          href.match(/\\/videos\\/([\\w-]+)/) ||
                          href.match(/\\/reel\\/([\\w-]+)/)   ||
                          href.match(/\\/permalink\\/([\\w-]+)/);
                if (m) { postId = m[1]; postUrl = a.href || ('https://www.facebook.com' + href); break; }
            }
            if (!postId || seen.has(postId)) continue;
            seen.add(postId);

            // Text
            let text = '';
            const textEl = art.querySelector('[data-ad-comet-preview="message"]') ||
                           art.querySelector('[data-ad-preview="message"]') ||
                           art.querySelector('[dir="auto"]');
            if (textEl) text = (textEl.innerText || '').trim().slice(0, 500);

            // Timestamp
            let ts = '';
            const timeEl = art.querySelector('abbr[data-utime],time[datetime]');
            if (timeEl) ts = timeEl.getAttribute('data-utime') || timeEl.getAttribute('datetime') || '';

            // Thumbnail
            let thumb = '';
            for (const img of art.querySelectorAll('img')) {
                const src = img.src || '';
                if ((src.includes('scontent') || src.includes('fbcdn')) &&
                    !src.includes('/p40x40/') && !src.includes('/p16x16/') &&
                    !src.includes('/p32x32/') && !src.includes('/p48x48/')) {
                    thumb = src; break;
                }
            }

            // Reactions
            let reactions = 0;
            const reactBar = art.querySelector(
                '[aria-label*="reaction"],[aria-label*="React"],[aria-label*="реакц"]'
            );
            if (reactBar) reactions = getBtnCount(reactBar);
            if (!reactions) {
                for (const btn of art.querySelectorAll('[role="button"]')) {
                    const lbl = (btn.getAttribute('aria-label') || '').toLowerCase();
                    if (lbl.includes('reaction') || lbl.includes('like') || lbl.includes('нравится')) {
                        const v = getBtnCount(btn);
                        if (v > 0) { reactions = v; break; }
                    }
                }
            }
            if (!reactions) {
                for (const span of art.querySelectorAll('span')) {
                    if (span.children.length > 0) continue;
                    const t = (span.textContent || '').trim();
                    if (!/^[\\d][\\d,.]*[KkMmBb]?$/.test(t)) continue;
                    const p = span.closest('[aria-label]');
                    if (!p) continue;
                    const pl = (p.getAttribute('aria-label') || '').toLowerCase();
                    if (pl.includes('react') || pl.includes('like') || pl.includes('нрав')) {
                        reactions = parseNum(t); break;
                    }
                }
            }

            // Comments
            let comments = 0;
            for (const btn of art.querySelectorAll('[role="button"],a')) {
                const lbl = (btn.getAttribute('aria-label') || btn.textContent || '').toLowerCase();
                if (lbl.includes('comment') || lbl.includes('коммент')) {
                    const v = getBtnCount(btn);
                    if (v > 0) { comments = v; break; }
                }
            }

            // Shares
            let shares = 0;
            for (const btn of art.querySelectorAll('[role="button"]')) {
                const lbl = (btn.getAttribute('aria-label') || '').toLowerCase();
                if (lbl.includes('share') || lbl.includes('поделиться')) {
                    const v = getBtnCount(btn);
                    if (v > 0) { shares = v; break; }
                }
            }

            // Views
            let views = 0;
            const viewsEl = art.querySelector(
                '[aria-label*="view"],[aria-label*="Views"],[aria-label*="просмотр"]'
            );
            if (viewsEl) views = getBtnCount(viewsEl);
            if (!views) {
                const vm = (art.innerText || '').match(
                    /([\\d][\\d\\s,.]*(?:млн|тыс|млрд|[KkMmBb])?)\\s*(?:views?|просмотр)/i
                );
                if (vm) views = parseNum(vm[1].trim());
            }

            results.push({ id: postId, url: postUrl, text, ts, thumb,
                           reactions, comments, shares, views });
        } catch(_) {}
    }
    return results;
}"""


_MBASIC_FALLBACK_JS = """(params) => {
    const username = String((params && params.username) || '');
    const maxPosts = Math.max(1, Number((params && params.maxPosts) || 8));
    const out = { followers: '', pageLikes: '', posts: [] };
    const bodyText = (document.body && document.body.innerText) ? document.body.innerText : '';
    const parseNum = (s) => (s || '').replace(/[\\u00a0\\u202f]/g, ' ').trim();

    const fMatch =
      bodyText.match(/([\\d][\\d\\s,.]*[KkMmBb]?)\\s+(?:followers?|подписчик\\w*)/i) ||
      bodyText.match(/(?:followers?|подписчик\\w*)\\s*[:\\-]?\\s*([\\d][\\d\\s,.]*[KkMmBb]?)/i);
    if (fMatch) out.followers = parseNum(fMatch[1]);

    const lMatch =
      bodyText.match(/([\\d][\\d\\s,.]*[KkMmBb]?)\\s+(?:likes?|нравится)/i) ||
      bodyText.match(/(?:likes?|нравится)\\s*[:\\-]?\\s*([\\d][\\d\\s,.]*[KkMmBb]?)/i);
    if (lMatch) out.pageLikes = parseNum(lMatch[1]);

    const links = document.querySelectorAll('a[href*="story_fbid="], a[href*="/posts/"], a[href*="/videos/"], a[href*="/reel/"], a[href*="/permalink/"]');
    const seen = new Set();
    for (const a of links) {
        if (out.posts.length >= maxPosts) break;
        const href = a.getAttribute('href') || '';
        let id = '';
        let m = href.match(/story_fbid=([\\w-]+)/) ||
                href.match(/\\/posts\\/([\\w-]+)/) ||
                href.match(/\\/videos\\/([\\w-]+)/) ||
                href.match(/\\/reel\\/([\\w-]+)/) ||
                href.match(/\\/permalink\\/([\\w-]+)/);
        if (m) id = m[1];
        if (!id || seen.has(id)) continue;
        seen.add(id);

        const row = (a.closest('article') || a.closest('div') || a.parentElement || document.body);
        const rowText = (row && row.innerText) ? row.innerText : '';
        const cm = rowText.match(/([\\d][\\d\\s,.]*[KkMmBb]?)\\s*(?:comments?|коммент)/i);
        const sm = rowText.match(/([\\d][\\d\\s,.]*[KkMmBb]?)\\s*(?:shares?|подел)/i);
        const vm = rowText.match(/([\\d][\\d\\s,.]*[KkMmBb]?)\\s*(?:views?|просмотр)/i);
        const rm = rowText.match(/([\\d][\\d\\s,.]*[KkMmBb]?)\\s*(?:reactions?|likes?|нрав)/i);
        out.posts.push({
            id,
            url: a.href || '',
            text: rowText.slice(0, 500),
            comments: cm ? parseNum(cm[1]) : '0',
            shares: sm ? parseNum(sm[1]) : '0',
            views: vm ? parseNum(vm[1]) : '0',
            reactions: rm ? parseNum(rm[1]) : '0',
            ts: '',
            thumb: '',
        });
    }
    return out;
}"""


async def _extract_mbasic_fallback(page, username: str) -> dict:
    """Fallback для Facebook: более простой HTML на mbasic."""
    try:
        await asyncio.sleep(_ms_jitter(PAUSE_PRE_M_BASIC_MIN_MS, PAUSE_PRE_M_BASIC_MAX_MS))
        await page.goto(
            f"https://mbasic.facebook.com/{username}?v=timeline",
            wait_until="domcontentloaded",
            timeout=NAV_TIMEOUT,
        )
        await page.wait_for_timeout(1800)
        data = await page.evaluate(_MBASIC_FALLBACK_JS, {"username": username, "maxPosts": MAX_POSTS})
        if not isinstance(data, dict):
            return {"followers": "", "pageLikes": "", "posts": []}
        return {
            "followers": str(data.get("followers") or ""),
            "pageLikes": str(data.get("pageLikes") or ""),
            "posts": data.get("posts") or [],
        }
    except Exception as exc:
        print(f"[facebook_worker] mbasic fallback failed: {exc}", file=sys.stderr)
        return {"followers": "", "pageLikes": "", "posts": []}


# ── Main ──────────────────────────────────────────────────────────────────────

def _load_worker_utils():
    import importlib.util as _ilu
    _wu_path = Path(__file__).parent.parent / "worker_utils.py"
    if not _wu_path.exists():
        raise RuntimeError("Внутренняя ошибка: worker_utils.py не найден.")
    _wu_spec = _ilu.spec_from_file_location("worker_utils", _wu_path)
    _wu = _ilu.module_from_spec(_wu_spec)
    _wu_spec.loader.exec_module(_wu)
    return _wu


async def _run_with_page(username: str, page, _wu):
    display_name   = username
    follower_count = 0
    like_count_val = 0
    avatar_url     = ""
    bio            = ""
    posts_raw      = []
    network_post_metrics: dict[str, dict] = {}

    async def _on_response(resp):
        await _capture_response_post_metrics(resp, network_post_metrics)

    page.on("response", lambda resp: asyncio.create_task(_on_response(resp)))

    # ── 1. Navigate ───────────────────────────────────────────────
    print(f"[facebook_worker] navigating to facebook.com/{username}", file=sys.stderr)
    await asyncio.sleep(_ms_jitter(PAUSE_PRE_NAV_MIN_MS, PAUSE_PRE_NAV_MAX_MS))
    await page.goto(
        f"https://www.facebook.com/{username}",
        wait_until="domcontentloaded",
        timeout=NAV_TIMEOUT,
    )
    await _wu.wait_for_anti_bot_clear(page, platform="facebook")

    # ── 2. Auth check ─────────────────────────────────────────────
    try:
        await page.wait_for_function(
            f"() => {{ const s = ({_STATE_JS})(); return s !== 'loading'; }}",
            timeout=AUTH_DETECT_TIMEOUT,
        )
    except Exception:
        pass

    state = await page.evaluate(_STATE_JS)
    print(f"[facebook_worker] state: {state!r}", file=sys.stderr)
    if state == "auth":
        print(
            "[facebook_worker] страница похожа на экран входа — "
            "продолжаем без сессии (публичные meta/main, если есть)",
            file=sys.stderr,
        )

    # ── 3. Wait for content ───────────────────────────────────────
    try:
        await page.wait_for_selector("h1, [role='main']", timeout=LOAD_TIMEOUT)
    except Exception:
        pass
    await page.wait_for_timeout(2500)

    # ── 4. Profile data ───────────────────────────────────────────
    info = await page.evaluate(_PROFILE_JS, username)

    display_name   = (info.get("displayName") or "").strip() or username
    follower_count = _parse_count(info.get("followers") or "")
    like_count_val = _parse_count(info.get("pageLikes") or "")
    avatar_url     = info.get("avatar") or ""
    bio            = info.get("bio") or ""
    print(
        f"[facebook_worker] name={display_name!r} "
        f"followers={follower_count} likes={like_count_val}",
        file=sys.stderr,
    )
    print(f"[facebook_worker] page snippet: {(info.get('dbg') or '')[:250]!r}",
          file=sys.stderr)
    print(f"[facebook_worker] pageLikes raw: {info.get('pageLikes')!r}",
          file=sys.stderr)
    print(f"[facebook_worker] нравится context: {info.get('dbgLikes')!r}",
          file=sys.stderr)
    for line in (info.get('likeDbg') or []):
        print(f"[facebook_worker] likeRe: {line}", file=sys.stderr)
    for line in (info.get('nravLines') or []):
        print(f"[facebook_worker] нравится line: {line}", file=sys.stderr)

    # ── 5. Scroll — stop early once MAX_POSTS links visible ───────
    for i in range(3):
        n = await page.evaluate("""() =>
            document.querySelectorAll(
                '[role="article"] a[href*="/posts/"],'  +
                '[role="article"] a[href*="story_fbid"],' +
                '[role="article"] a[href*="/videos/"],' +
                '[role="article"] a[href*="/reel/"]'
            ).length
        """)
        print(f"[facebook_worker] scroll {i}: {n} post-links visible", file=sys.stderr)
        if n >= MAX_POSTS:
            break
        await page.keyboard.press("End")
        await asyncio.sleep(_ms_jitter(PAUSE_SCROLL_MIN_MS, PAUSE_SCROLL_MAX_MS))
    await page.wait_for_timeout(1000)

    # ── 6. Extract posts ──────────────────────────────────────────
    posts_raw = await page.evaluate(_POSTS_JS, {"username": username, "maxPosts": MAX_POSTS})

    # ── 7. Fallback to mbasic when data is sparse ────────────────────────────
    mbasic_data = {"followers": "", "pageLikes": "", "posts": []}
    if (len(posts_raw) < 3) or (follower_count <= 0):
        mbasic_data = await _extract_mbasic_fallback(page, username)
        fb_fallback = _parse_count(mbasic_data.get("followers", ""))
        likes_fallback = _parse_count(mbasic_data.get("pageLikes", ""))
        if fb_fallback > follower_count:
            follower_count = fb_fallback
        if likes_fallback > like_count_val:
            like_count_val = likes_fallback
        # Merge posts by external id
        existing_ids = {str(p.get("id", "")).strip() for p in posts_raw if p.get("id")}
        for row in (mbasic_data.get("posts") or []):
            rid = str(row.get("id", "")).strip()
            if rid and rid not in existing_ids:
                posts_raw.append(row)
                existing_ids.add(rid)

    # ── 8. Post-process ───────────────────────────────────────────────────────
    posts = []
    for p in posts_raw:
        post_id = str(p.get("id", "")).strip()
        if not post_id:
            continue
        nmeta = network_post_metrics.get(post_id) or {}
        ts = p.get("ts", "")
        posted_at = None
        if ts:
            try:
                posted_at = datetime.fromtimestamp(int(ts), tz=timezone.utc).isoformat()
            except Exception:
                try:
                    posted_at = datetime.fromisoformat(ts.replace("Z", "+00:00")).isoformat()
                except Exception:
                    pass
        posts.append({
            "external_id":   post_id,
            "description":   p.get("text", ""),
            "thumbnail_url": p.get("thumb", ""),
            "post_url":      nmeta.get("post_url") or p.get("url", f"https://www.facebook.com/{username}/posts/{post_id}"),
            "view_count":    max(_parse_count(p.get("views", 0)), int(nmeta.get("views", 0) or 0)),
            "like_count":    max(_parse_count(p.get("reactions", 0)), int(nmeta.get("reactions", 0) or 0)),
            "comment_count": max(_parse_count(p.get("comments", 0)), int(nmeta.get("comments", 0) or 0)),
            "share_count":   max(_parse_count(p.get("shares", 0)), int(nmeta.get("shares", 0) or 0)),
            "posted_at":     posted_at,
        })

    print(f"[facebook_worker] extracted {len(posts)} posts", file=sys.stderr)

    return {
        "display_name":   display_name,
        "avatar_url":     avatar_url,
        "bio":            bio,
        "follower_count": follower_count,
        "like_count":     like_count_val,
        "post_count":     len(posts) or None,
        "_posts":         posts,
        "_quality_flags": {
            "auth_wall_detected": state == "auth",
            "network_metrics_used": len(network_post_metrics) > 0,
            "mbasic_fallback_used": bool(mbasic_data.get("posts") or mbasic_data.get("followers") or mbasic_data.get("pageLikes")),
            "partial_posts": len(posts) < max(3, min(MAX_POSTS, 8)),
        },
    }


async def run_once(arg: dict):
    arg = dict(arg)
    username = arg["username"].lstrip("@")
    _wu = _load_worker_utils()
    try:
        async with async_playwright() as pw:
            context, _browser = await _wu.launch_context(
                pw, platform="facebook",
                locale="ru-RU", force_persistent=True,
            )
            page = context.pages[0] if context.pages else await context.new_page()
            try:
                return await _run_with_page(username, page, _wu)
            finally:
                await _wu.close_context(context, _browser)
    except Exception as exc:
        print(f"[facebook_worker] exception: {exc}", file=sys.stderr)
        return {"error": f"Ошибка: {exc}"}


def _write_response(payload: dict) -> None:
    from platforms.worker_json_stdout import write_json_line

    write_json_line(payload)


async def daemon_main() -> None:
    _wu = _load_worker_utils()
    async with async_playwright() as pw:
        context, _browser = await _wu.launch_context(
            pw, platform="facebook",
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
                except Exception as exc:
                    _write_response({"error": f"Ошибка worker: {exc}"})
                    continue
                _write_response(result)
                await asyncio.sleep(_ms_jitter(PAUSE_BETWEEN_TASKS_MIN_MS, PAUSE_BETWEEN_TASKS_MAX_MS))
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
