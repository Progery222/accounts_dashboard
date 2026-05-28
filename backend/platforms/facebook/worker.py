"""
Standalone subprocess — fetches Facebook Page / profile data.
Invoked by Django через worker_pool как ``python .../worker.py --daemon`` (одно окно Chromium на процесс).

Отладка вручную: ``python platforms/facebook/worker.py --once path/to/payload.json``
или ``--once '{"username":"pagename"}'``; либо ``python .../worker.py --daemon`` со строками JSON в stdin;

Если есть ``facebook_state.json`` (импорт cookies в Настройках) — сессия из него;
иначе persistent-профиль ``…/facebook_persistent`` или общий каталог AccountsStats.
Runs headless=False with the window placed off-screen.

Публичный скрапинг без обязательного входа: при «стене» логина всё равно
пытаемся вытащить og:title / main — раньше жёстко падали на ложном auth.

Переход **ровно два раза** на www: (1) основной URL профиля (без ``sk=…``),
(2) тот же профиль с ``sk=reels_tab`` — вкладка Reels (``page.goto``, без клика по UI).
После (2) **не** уходим на mbasic/timeline за подписчиками, если уже на ``sk=reels_tab`` —
это давало лишний «уход с Reels на профиль». Запасной mbasic только если
``FACEBOOK_MBASIC_FALLBACK=1`` и страница **не** на www ``sk=reels_tab``.
Опционально: ``FACEBOOK_REELS_UI_CLICK_FALLBACK=1`` или ``FACEBOOK_PHOTOS_UI_CLICK_FALLBACK=1`` —
если после (2) в URL нет ``sk=reels_tab``, один раз пробуем клик по вкладке Reels.

Детальные лайки Reels: **одно открытие на пост** — либо клик по карточке на сетке (модалка),
либо (если нет ``sk=reels_tab`` / mbasic) один ``page.goto`` на URL Reel и возврат на сетку;
**не** цепочка «клик + goto» для одного и того же ролика. Счётчик — у **верхней видимой**
кнопки «Нравится» в viewport (модалка или ``/reel/…``); **нет цифры = 0** (``like_count_confirmed``).
На прямом ``/reel/…`` не берём max по aria-label соседних роликов в ленте. По умолчанию **включено**
(``FACEBOOK_DETAIL_LIKES_ENABLED=0`` — выключить). Перед кликом по карточке при необходимости
**возврат на URL с sk=reels_tab** — после модалки Facebook часто уводит со вкладки.
Порог просмотров: ``FACEBOOK_DETAIL_LIKES_MIN_VIEWS`` (по умолчанию **2000**): у постов с
``view_count ≤`` порогу лайки с сетки сбрасываются (**0**). Detail-enrich по умолчанию только для
постов со **строго большим** числом просмотров: ``view_count > MIN_VIEWS`` (без лавины modal на
все низкие Reels). Опционально снова обогащать низкие Reels: ``FACEBOOK_DETAIL_ENRICH_LOW_VIEW_REELS=1``.
Эвристика «лайки = просмотры» (обнуление): ``FACEBOOK_REEL_LIKE_VIEW_EQUAL_MAX_V`` (по умолчанию 12_000),
раньше по сути действовало до 500k и могло сбрасывать лайки у роликов с ~16k просмотров при ошибочном совпадении парсера.
До ``FACEBOOK_DETAIL_LIKES_MAX_OPENS`` постов за проход (по умолчанию 30, не более 50; ветка enrich
отключена, если ``FACEBOOK_DETAIL_LIKES_ENABLED=0``). Сколько постов собирать с ленты: ``FACEBOOK_MAX_POSTS``
(по умолчанию 80, верхняя граница 120).
XPath текста лайков: ``FACEBOOK_POST_LIKES_XPATH`` или встроенный дефолт
(хрупко при смене вёрстки Facebook).
Одноразовый запуск ``run_once`` / ``--once``: по умолчанию окно не закрывается после
ответа в stdout (как у демона); автозакрытие: ``WORKER_AUTOCLOSE_BROWSER_ON_EXIT=1``.
Устарело: ``FACEBOOK_RUN_ONCE_KEEP_BROWSER`` — поведение совпадает с дефолтом.

После окончания stdin демон **не** вызывает ``close_context``: окно остаётся,
процесс ждёт бесконечно (закрытие — остановка worker-процесса / Django /
``shutdown_all_workers``). Для явного закрытия при выходе процесса:
``FACEBOOK_DAEMON_CLOSE_BROWSER_ON_EXIT=1`` или глобально
``WORKER_AUTOCLOSE_BROWSER_ON_EXIT=1``. Чтобы при остановке Django не
убивать воркеры через atexit: ``PLAYWRIGHT_POOL_SKIP_ATEXIT=1`` (осторожно: зомби Chromium).
"""
import asyncio
import json
import os
import random
import re
import sys
from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path

from playwright.async_api import async_playwright

from platforms.facebook.profile_meta import (
    is_usable_facebook_avatar_url,
    sanitize_facebook_display_name,
)
from platforms.facebook.profile_url import normalize_facebook_profile_input

NAV_TIMEOUT         = 35_000
LOAD_TIMEOUT        = 25_000
AUTH_DETECT_TIMEOUT = 12_000
try:
    _fb_max_posts_raw = int(os.getenv("FACEBOOK_MAX_POSTS", "80") or "80")
except (TypeError, ValueError):
    _fb_max_posts_raw = 80
MAX_POSTS = max(1, min(120, _fb_max_posts_raw))
PAUSE_PRE_NAV_MIN_MS = int(os.getenv("FACEBOOK_PAUSE_PRE_NAV_MIN_MS", "700") or "700")
PAUSE_PRE_NAV_MAX_MS = int(os.getenv("FACEBOOK_PAUSE_PRE_NAV_MAX_MS", "1700") or "1700")
PAUSE_SCROLL_MIN_MS = int(os.getenv("FACEBOOK_PAUSE_SCROLL_MIN_MS", "900") or "900")
PAUSE_SCROLL_MAX_MS = int(os.getenv("FACEBOOK_PAUSE_SCROLL_MAX_MS", "1900") or "1900")
PAUSE_PRE_M_BASIC_MIN_MS = int(os.getenv("FACEBOOK_PAUSE_PRE_MBASIC_MIN_MS", "800") or "800")
PAUSE_PRE_M_BASIC_MAX_MS = int(os.getenv("FACEBOOK_PAUSE_PRE_MBASIC_MAX_MS", "1800") or "1800")
PAUSE_BETWEEN_TASKS_MIN_MS = int(os.getenv("FACEBOOK_PAUSE_BETWEEN_TASKS_MIN_MS", "1000") or "1000")
PAUSE_BETWEEN_TASKS_MAX_MS = int(os.getenv("FACEBOOK_PAUSE_BETWEEN_TASKS_MAX_MS", "2200") or "2200")

# Детальные лайки Reels (XPath к узлу с цифрой лайков после открытия поста).
# Блок «лайк + иконка» (шире): …/div[2]/div[1]/div[3]/div/div/div[2]/div/div/div/div/div/div/div[1]
# — при смене вёрстки можно подставить через FACEBOOK_POST_LIKES_XPATH узел с текстом или span.
_DEFAULT_FB_REEL_LIKES_XPATH = (
    "/html/body/div[1]/div/div[1]/div/div[5]/div/div/div[3]/div[2]/div/div/div/div/"
    "div/div/div/div[2]/div[1]/div[3]/div/div/div[2]/div/div/div/div/div/div/div[1]/"
    "div/div[1]/div/div[1]/div/div[2]/div/span/span"
)


def _facebook_detail_likes_enabled() -> bool:
    return os.getenv("FACEBOOK_DETAIL_LIKES_ENABLED", "1").strip().lower() not in {
        "0", "false", "no", "off",
    }


def _facebook_detail_likes_min_views() -> int:
    """Порог просмотров для детальных лайков (env ``FACEBOOK_DETAIL_LIKES_MIN_VIEWS``, по умолчанию 2000)."""
    try:
        return max(0, int(os.getenv("FACEBOOK_DETAIL_LIKES_MIN_VIEWS", "2000") or "2000"))
    except (TypeError, ValueError):
        return 2000


def _facebook_detail_enrich_low_view_reels() -> bool:
    """
    По умолчанию **выкл.**: не открывать в modal каждый Reel с ``view_count ≤`` порога
    (иначе лавина кликов и лишние ``goto``). Вкл.: ``FACEBOOK_DETAIL_ENRICH_LOW_VIEW_REELS=1``.
    """
    return os.getenv("FACEBOOK_DETAIL_ENRICH_LOW_VIEW_REELS", "").strip().lower() in {
        "1", "true", "yes", "on",
    }



# Reels: лайки у видимой кнопки «Нравится» (верхняя в viewport); нет цифры = 0.
_FB_VISIBLE_REEL_LIKE_JS = """() => {
    const clean = (s) => String(s || '').replace(/[\\u00a0\\u202f]/g, ' ').replace(/\\s+/g, ' ').trim();
    const likeRe = /\\u043d\\u0440\\u0430\\u0432|лайк|\\breaction|\\blike\\b|\\u00ab\\u041d\\u0440\\u0430\\u0432\\u0438\\u0442\\u0441\\u044f\\u00bb|мне нравится/i;
    const viewRe = /просмотр|\\bviews?\\b|watch|play|воспроизвед/i;
    function tryDigits(raw) {
        const t = clean(String(raw || ''));
        if (!/^\\d{1,7}$/.test(t)) return 0;
        const n = parseInt(t, 10);
        return (n >= 0 && n < 9999999) ? n : 0;
    }
    function scanTextFrom(el) {
        if (!el) return 0;
        let n = tryDigits(el.innerText) || tryDigits(el.textContent);
        if (n) return n;
        for (const sp of el.querySelectorAll('span')) {
            n = tryDigits(sp.innerText);
            if (n) return n;
        }
        let w = el.nextElementSibling;
        for (let s = 0; s < 6 && w && !n; s++, w = w.nextElementSibling)
            n = scanTextFrom(w);
        if (!n && el.parentElement) {
            const ch = [...el.parentElement.children];
            const ix = ch.indexOf(el);
            for (let k = ix + 1; k < Math.min(ix + 6, ch.length) && !n; k++)
                n = scanTextFrom(ch[k]);
        }
        return n || 0;
    }
    function readIn(root) {
        const scope = root || document;
        let topBtn = null;
        let topY = 1e9;
        for (const el of scope.querySelectorAll('[role="button"][aria-label], [aria-pressed][aria-label]')) {
            const a = clean(el.getAttribute('aria-label') || '');
            if (!a || a.length > 240 || !likeRe.test(a) || viewRe.test(a)) continue;
            if (/комментар|комменти|\\bcomment\\b|поделиться|\\bshare\\b|отправить|^send\\b/i.test(a) && !likeRe.test(a))
                continue;
            const rect = el.getBoundingClientRect();
            if (rect.width < 1 || rect.height < 1) continue;
            if (rect.top < -40 || rect.top > innerHeight - 80) continue;
            if (rect.top < topY) { topY = rect.top; topBtn = el; }
        }
        if (!topBtn) return null;
        return scanTextFrom(topBtn);
    }
    const dlg = document.querySelector('[role="dialog"],[aria-modal="true"]');
    if (dlg) {
        const v = readIn(dlg);
        if (v !== null) return { found: true, digit: v };
    }
    if (/\\/reel\\/\\d+/i.test(location.pathname || '')) {
        const main = document.querySelector('[role="main"]') || document.body;
        const v = readIn(main);
        if (v !== null) return { found: true, digit: v };
    }
    return { found: false, digit: 0 };
}"""

_FB_XPATH_LIKE_TEXT_JS = """(xp) => {
    try {
        const r = document.evaluate(
            xp, document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null
        );
        const el = r.singleNodeValue;
        if (el && el.textContent)
            return String(el.textContent).trim().slice(0, 48);
    } catch (e) {}
    return '';
}"""


_FB_FALLBACK_LIKES_TEXT_JS = """() => {
    const clean = (s) => String(s || '').replace(/[\\u00a0\\u202f]/g, ' ').replace(/\\s+/g, ' ').trim();
    function parseCompact(t) {
        let s = clean(t || '').trim();
        const ru = s.match(/^([\\d]+(?:[.,][\\d]+)?)\\s*(млрд|млн|тыс)\\.?/i);
        if (ru) {
            const n = parseFloat(ru[1].replace(',', '.'));
            const m = { млн: 1e6, тыс: 1e3, млрд: 1e9 }[ru[2].toLowerCase()] || 1;
            return Math.round(n * m);
        }
        s = s.replace(/[\\s,]/g, '').replace(',', '.');
        const la = s.match(/^([\\d]+(?:\\.[\\d]+)?)([KkMmBb]?)$/);
        if (!la) return 0;
        const mult = { K: 1e3, M: 1e6, B: 1e9 }[la[2].toUpperCase()] || 1;
        return Math.round(parseFloat(la[1]) * mult);
    }
    function numFromLikeLabel(a) {
        if (!a || a.length > 320) return 0;
        if (/просмотр|\\bviews?\\b|\\bwatch\\b|play count|воспроизвед/i.test(a)) return 0;
        if (/комментар|\\bcomments?\\b|подел|shares?/i.test(a) && !/нравится|лайк|reaction|\\blike\\b/i.test(a))
            return 0;
        const patterns = [
            /([\\d][\\d\\s.,]*\\s*(?:млрд|млн|тыс)\\.?)\\s*(?:отметок\\s*«?Нравится»?|reactions?|лайков?)/i,
            /([\\d][\\d\\s.,]*)\\s*(?:отметок\\s*«?Нравится»?|reactions?|лайков?)/i,
            /([\\d][\\d\\s.,]*)\\s*нравится/i,
            /нравится[:\\s]+([\\d][\\d\\s.,]*\\s*(?:млрд|млн|тыс)\\.?)/i,
            /нравится[:\\s]+([\\d][\\d\\s.,]*)/i,
            /(?:reactions?|likes?|лайк\\w*)[:\\s]+([\\d][\\d\\s.,]*\\s*(?:млрд|млн|тыс)\\.?)/i,
            /(?:reactions?|likes?|лайк\\w*)[:\\s]+([\\d][\\d\\s.,]*)/i,
            /(?:^|[\\s"«(])([\\d][\\d\\s.,]*)\\s*(?:people|person|persons)\\s+(?:liked|like)/i,
        ];
        for (const re of patterns) {
            const m = a.match(re);
            if (m) {
                const n = parseCompact(m[1].trim());
                if (n > 0 && n < 1e9) return n;
            }
        }
        return 0;
    }
    /** Reels: цифра под видимой кнопкой «Нравится» (верхняя в viewport), не max по всей ленте. */
    function digitBelowLikeControl(container) {
        if (!container) return 0;
        function tryDigits(raw) {
            const t = clean(String(raw || ''));
            if (!/^\\d{1,7}$/.test(t)) return 0;
            const n = parseInt(t, 10);
            return (n >= 0 && n < 9999999) ? n : 0;
        }
        function scanTextFrom(el) {
            if (!el) return 0;
            let n = tryDigits(el.innerText) || tryDigits(el.textContent);
            if (n) return n;
            for (const sp of el.querySelectorAll('span')) {
                n = tryDigits(sp.innerText);
                if (n) return n;
            }
            let w = el.nextElementSibling;
            for (let s = 0; s < 6 && w && !n; s++, w = w.nextElementSibling)
                n = scanTextFrom(w);
            if (!n && el.parentElement) {
                const ch = [...el.parentElement.children];
                const ix = ch.indexOf(el);
                for (let k = ix + 1; k < Math.min(ix + 6, ch.length) && !n; k++)
                    n = scanTextFrom(ch[k]);
            }
            return n || 0;
        }
        let topBtn = null;
        let topY = 1e9;
        for (const el of container.querySelectorAll('[role="button"][aria-label], [aria-pressed][aria-label]')) {
            const a = clean(el.getAttribute('aria-label') || '');
            if (!a || a.length > 240) continue;
            if (/просмотр|\\bviews?\\b|watch|play|воспроизвед/i.test(a)) continue;
            if (/комментар|комменти|\\bcomment\\b|поделиться|\\bshare\\b|отправить|^send\\b/i.test(a) && !/нравится|like|лайк/i.test(a)) continue;
            if (!/нравится|лайк|\\breaction|\\blike\\b|«Нравится»|мне нравится/i.test(a)) continue;
            if (numFromLikeLabel(a) > 0) continue;
            const rect = el.getBoundingClientRect();
            if (rect.width < 1 || rect.height < 1) continue;
            if (rect.top < -40 || rect.top > innerHeight - 80) continue;
            if (rect.top < topY) { topY = rect.top; topBtn = el; }
        }
        return topBtn ? scanTextFrom(topBtn) : 0;
    }
    const onDirectReel = /\\/reel\\/\\d+/i.test(location.pathname || '');
    const roots = [];
    for (const d of document.querySelectorAll('[role="dialog"],[aria-modal="true"]')) roots.push(d);
    const m0 = document.querySelector('[role="main"]');
    if (m0) roots.push(m0);
    let best = 0;
    // На прямом /reel/… max по aria-label цепляет соседние ролики в ленте — только digitBelowLikeControl.
    if (!onDirectReel) {
        for (const r of roots) {
            if (!r) continue;
            for (const el of r.querySelectorAll('[aria-label]')) {
                const a = clean(el.getAttribute('aria-label'));
                if (!a) continue;
                if (!/нравится|лайк|\\breaction|\\blike\\b|«Нравится»/i.test(a)) continue;
                const n = numFromLikeLabel(a);
                if (n > best) best = n;
            }
            for (const el of r.querySelectorAll('[role="button"][aria-label]')) {
                const a = clean(el.getAttribute('aria-label'));
                if (!a) continue;
                if (!/нравится|лайк|\\breaction|\\blike\\b/i.test(a)) continue;
                const n = numFromLikeLabel(a);
                if (n > best) best = n;
            }
        }
        for (const el of document.querySelectorAll('[aria-pressed]')) {
            const a = clean(el.getAttribute('aria-label') || '');
            if (!a || !/нравится|лайк|\\breaction|\\blike\\b|«Нравится»/i.test(a)) continue;
            if (/просмотр|\\bviews?\\b/i.test(a)) continue;
            const v = numFromLikeLabel(a);
            if (v > best) best = v;
        }
    }
    const passRoots = roots.length ? roots : [document.body];
    for (const r of passRoots) {
        if (!r) continue;
        const d = digitBelowLikeControl(r);
        if (d > best) best = d;
    }
    if (best > 0) return String(best);
    if (onDirectReel) return '';
    const blob = clean((document.body && document.body.innerText) || '').slice(0, 20000);
    for (const ln of blob.split(/[\\n\\r]+/)) {
        const t = ln.trim();
        if (!t || t.length > 120 || /просмотр|\\bviews?\\b|watch/i.test(t)) continue;
        const m = t.match(/^([\\d][\\d\\s.,]*(?:\\s*(?:млрд|млн|тыс)\\.?)?)\\s*(?:нравится|likes?|reactions?|лайк)/i);
        if (m) {
            const n = parseCompact(m[1].trim());
            if (n > best) best = n;
        }
    }
    return best > 0 ? String(best) : '';
}"""


def _facebook_mbasic_fallback_enabled() -> bool:
    """Второй переход на mbasic — только по явному env (по умолчанию выключено)."""
    return os.getenv("FACEBOOK_MBASIC_FALLBACK", "").strip().lower() in {"1", "true", "yes", "on"}


def _facebook_daemon_should_close_browser_on_exit() -> bool:
    """Закрыть Chromium при завершении stdin только по явному env."""
    try:
        from platforms.worker_utils import worker_autoclose_browser_on_daemon_exit

        if worker_autoclose_browser_on_daemon_exit():
            return True
    except Exception:
        pass
    return os.getenv("FACEBOOK_DAEMON_CLOSE_BROWSER_ON_EXIT", "").strip().lower() in {
        "1", "true", "yes", "on",
    }


def _ms_jitter(min_ms: int, max_ms: int) -> float:
    lo = max(0, min_ms)
    hi = max(lo, max_ms)
    return random.uniform(lo, hi) / 1000.0


def _iter_incoming_json_lines(cli_first_json: str | None) -> Iterator[str]:
    """Сначала опциональная строка из argv (CLI), затем строки stdin (демон Django)."""
    if cli_first_json is not None:
        s = cli_first_json.strip()
        if s:
            yield s
    for line in sys.stdin:
        s = line.strip()
        if s:
            yield s


# ── Python parse helper ───────────────────────────────────────────────────────


def _parse_like_count_from_aria_label(lab: str) -> int:
    """
    aria-label кнопки лайка на Reels: часто «…у 9 пользователей» / «9 отметок …».
    Общий ``_parse_count`` режет строку по «нравится» и может потерять число.
    """
    if not lab:
        return 0
    s = str(lab).strip()
    patterns = (
        r'(\d[\d\s.,]*)\s*(?:пользовател\w*|people|persons?)\b',
        r'(\d[\d\s.,]*)\s*(?:отметок|reactions?|likes?)\b',
        r'(?:^|[\s,;])(\d{1,7})\s*(?:people|person|пользовател)',
        r'[:\s]\s*(\d{1,7})\s*$',
    )
    for pat in patterns:
        m = re.search(pat, s, re.I)
        if m:
            digits = re.sub(r'[^\d]', '', m.group(1))
            if digits:
                n = int(digits)
                if 0 < n < 50_000_000:
                    return n
    return 0


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


def _facebook_zero_like_if_equals_views(posts: list[dict]) -> None:
    """
    Совпадение like_count и view_count на **небольших** числах — почти всегда артефакт DOM.
    Раньше верхняя граница была 500k — при ~16k просмотров ложное совпадение парсера
    обнуляло реальные лайки. Сейчас порог задаётся ``FACEBOOK_REEL_LIKE_VIEW_EQUAL_MAX_V``
    (по умолчанию 12_000); ``0`` — отключить эвристику.
    """
    try:
        max_v = int(os.getenv("FACEBOOK_REEL_LIKE_VIEW_EQUAL_MAX_V", "12000") or "12000")
    except (TypeError, ValueError):
        max_v = 12_000
    if max_v <= 0:
        return
    for p in posts:
        v = int(p.get("view_count") or 0)
        l = int(p.get("like_count") or 0)
        if l > 0 and l == v and v <= max_v:
            p["like_count"] = 0


def _facebook_dedupe_phantom_likes(posts: list[dict]) -> None:
    """
    Одинаковый положительный like_count у нескольких постов с сильно разными просмотрами —
    типичный «фантом» (DOM/GraphQL). Обнуляем такую группу.
    """
    from collections import defaultdict

    by_like: dict[int, list[dict]] = defaultdict(list)
    for p in posts:
        lk = int(p.get("like_count") or 0)
        if lk > 0:
            by_like[lk].append(p)
    for k, group in by_like.items():
        if k < 2 or len(group) < 3:
            continue
        views_set = {int(p.get("view_count") or 0) for p in group}
        if len(views_set) < 3:
            continue
        for p in group:
            p["like_count"] = 0


def _facebook_zero_likes_if_like_is_other_post_view_count(posts: list[dict]) -> None:
    """
    like_count близок к view_count *какого-то* поста в той же выборке (но не к просмотрам
    этого поста) — типично «первое число на странице» подтянуло чужие просмотры; во время
    скрапа просмотры растут, поэтому совпадение не обязано быть точным (162 vs 163/166).
    Малые числа не трогаем (случайные совпадения).
    """
    floor = int(os.getenv("FACEBOOK_LIKE_VIEW_COLLISION_MIN", "30") or "30")
    drift = int(os.getenv("FACEBOOK_LIKE_VIEW_COLLISION_DRIFT", "8") or "8")
    if drift < 0:
        drift = 0
    view_vals = [int(p.get("view_count") or 0) for p in posts if int(p.get("view_count") or 0) > 0]
    if not view_vals:
        return
    for p in posts:
        v = int(p.get("view_count") or 0)
        l = int(p.get("like_count") or 0)
        if l < max(1, floor) or l <= 0:
            continue
        if l == v:
            continue
        nearest = min(abs(l - x) for x in view_vals)
        if nearest <= drift:
            p["like_count"] = 0


def _fb_aria_label_looks_like_views(text: str) -> bool:
    if not text:
        return False
    return bool(
        re.search(
            r"просмотр|\bviews?\b|\bwatch\b|play\s*count|воспроизвед|played|\bviewers\b",
            str(text),
            re.I,
        ),
    )


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


def _facebook_reel_numeric_id_for_enrich(post: dict) -> str:
    """
    Числовой id ролика для detail-likes. В ленте часто только ``/posts/{id}`` / ``story_fbid``,
    без ``/reel/`` в URL — раньше enrich полностью пропускал такие посты.
    """
    url = str(post.get("post_url") or "").strip()
    eid = str(post.get("external_id") or "").strip()
    m = re.search(r"/reel/(\d+)", url, re.I)
    if m:
        return m.group(1)
    if eid.isdigit() and len(eid) >= 10:
        return eid
    for pat in (
        r"/posts/(\d{10,})",
        r"/videos/(\d{10,})",
        r"/permalink/(\d{10,})",
        r"story_fbid=(\d{10,})",
        r"fbid=(\d{10,})",
    ):
        mx = re.search(pat, url, re.I)
        if mx:
            rid = mx.group(1)
            if not eid or rid == eid:
                return rid
    return ""


def _facebook_url_for_reel_enrich(post: dict, reel_id: str) -> str:
    """URL для ``goto`` / same-tab: канонический ``/reel/{id}``, если в ``post_url`` нет ``/reel/``."""
    url = str(post.get("post_url") or "").strip()
    if "/reel/" in url.lower() and reel_id in url.replace("\\", "/"):
        return url
    return f"https://www.facebook.com/reel/{reel_id}"


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

        if (
            metrics["reactions"] > 0
            and metrics["views"] > 0
            and metrics["reactions"] == metrics["views"]
            and metrics["views"] <= 500_000
        ):
            metrics["reactions"] = 0

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

_FACEBOOK_RATE_LIMIT_JS = """
    () => {
        const title = (document.title || '').toLowerCase();
        const markers = [
            'временно заблокирован',
            'temporarily blocked',
            'слишком часто использовали',
            'using this feature too often',
            'we temporarily blocked',
            "you're temporarily blocked",
            'you are temporarily blocked',
        ];
        const roots = [];
        for (const sel of ['[role="dialog"]', '[role="alert"]', 'div[aria-modal="true"]']) {
            document.querySelectorAll(sel).forEach(el => roots.push(el));
        }
        const main = document.querySelector('[role="main"]');
        if (main) roots.push(main);
        if (!roots.length && document.body) roots.push(document.body);
        for (const root of roots) {
            const text = ((root && root.innerText) || '').toLowerCase();
            for (const m of markers) {
                if (text.includes(m) || title.includes(m)) {
                    return { blocked: true, marker: m };
                }
            }
        }
        return { blocked: false, marker: '' };
    }
"""


async def _facebook_raise_if_rate_limited(page, *, stage: str) -> None:
    from platforms.facebook.rate_limit import FACEBOOK_RATE_LIMIT_PREFIX

    try:
        data = await page.evaluate(_FACEBOOK_RATE_LIMIT_JS)
    except Exception:
        return
    if not isinstance(data, dict) or not data.get("blocked"):
        return
    marker = str(data.get("marker") or "").strip()
    hint = f" ({marker})" if marker else ""
    raise ValueError(
        f"{FACEBOOK_RATE_LIMIT_PREFIX} ({stage}){hint}. "
        "Подождите 15–60 мин, не жмите «Обновить» в цикле."
    )


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
    const badDisplay = (s) => {
        s = (s || '').trim();
        if (!s || s.length > 120) return true;
        return /уведомлен|notification|поиск|search|меню|menu|^\\d+$|^photo$/i.test(s);
    };
    const ogTitle = document.querySelector('meta[property="og:title"]');
    if (ogTitle) {
        const ogName = (ogTitle.getAttribute('content') || '').trim()
            .replace(/\\s*\\|\\s*Facebook.*$/i, '')
            .replace(/\\s*[-\\u2013]\\s*Facebook.*$/i, '')
            .trim();
        if (!badDisplay(ogName)) displayName = ogName;
    }
    if (!displayName) {
        for (const h of document.querySelectorAll('[data-pagelet] h1,[role="main"] h1,h1')) {
            const t = (h.textContent || '').trim();
            if (t && !badDisplay(t)) { displayName = t; break; }
        }
    }
    if (!displayName) {
        const titleName = document.title
            .replace(/\\s*\\|\\s*Facebook.*$/i, '')
            .replace(/\\s*[-\\u2013]\\s*Facebook.*$/i, '')
            .trim();
        if (!badDisplay(titleName)) displayName = titleName;
    }

    function svgImageHref(el) {
        if (!el) return '';
        return (el.getAttribute('href') || el.getAttribute('xlink:href') || '').trim();
    }

    // ── Avatar (+ имя из aria-label ссылки на фото) ─────────────────────────
    let avatar = '';
    const ogImg = document.querySelector('meta[property="og:image"]');
    if (ogImg) avatar = (ogImg.getAttribute('content') || '').trim();
    const photoLink = document.querySelector(
        '[role="main"] a[href*="/photo/"][aria-label], ' +
        '[role="main"] a[href*="fbid="][aria-label], ' +
        'header a[href*="/photo/"][aria-label], ' +
        'a[href*="facebook.com/photo"][aria-label]'
    );
    if (photoLink) {
        const lab = (photoLink.getAttribute('aria-label') || '').trim();
        if (lab && !badDisplay(lab)) displayName = lab;
        const svgIm = photoLink.querySelector('svg image');
        const h = svgImageHref(svgIm);
        if (h && (h.includes('scontent') || h.includes('fbcdn')) &&
            !h.includes('emoji.php') && !/\\/1f[0-9a-f]{2}/i.test(h)) {
            avatar = h;
        }
    }
    if (!avatar) {
        for (const ie of document.querySelectorAll('[role="main"] svg image, header svg image, [role="banner"] svg image')) {
            const h = svgImageHref(ie);
            if (h && (h.includes('scontent') || h.includes('fbcdn')) &&
                !h.includes('emoji.php') && !/\\/1f[0-9a-f]{2}/i.test(h) &&
                !h.includes('/p40x40/') && !h.includes('/p16x16/') &&
                !h.includes('/p32x32/') && !h.includes('/p48x48/')) {
                avatar = h; break;
            }
        }
    }
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
    if (badDisplay(displayName) && photoLink) {
        const lab2 = (photoLink.getAttribute('aria-label') || '').trim();
        if (lab2 && !badDisplay(lab2)) displayName = lab2;
    }

    // ── sk=reels_tab: первое фото до заголовка Reels (если есть) — кандидат в аватар ───
    if ((location.search || '').includes('sk=reels_tab') ||
        (location.href || '').toLowerCase().includes('sk%3dreels_tab')) {
        const mainEl = document.querySelector('[role="main"]');
        if (mainEl) {
            let reelsM = null;
            for (const el of mainEl.querySelectorAll('span, strong, h2, div[role="heading"], a')) {
                const t = (el.textContent || '').trim();
                if (/^Reels$/i.test(t) || /Видео\\s+Reels/i.test(t)) { reelsM = el; break; }
            }
            for (const pa of mainEl.querySelectorAll('a[href*="/photo/"]')) {
                const hr = pa.getAttribute('href') || '';
                if (!/fbid=/i.test(hr)) continue;
                if (reelsM && !(reelsM.compareDocumentPosition(pa) & Node.DOCUMENT_POSITION_PRECEDING)) continue;
                const sih = svgImageHref(pa.querySelector('svg image'));
                const ig = pa.querySelector('img');
                const cand = (sih || (ig && ig.src) || '').trim();
                if (cand && (cand.includes('scontent') || cand.includes('fbcdn')) &&
                    !cand.includes('emoji.php')) {
                    avatar = cand;
                    const labp = (pa.getAttribute('aria-label') || '').trim();
                    if (labp && !badDisplay(labp)) displayName = labp;
                    break;
                }
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
    if (!pageLikes) {
        for (const a of document.querySelectorAll(
            '[role="banner"] a,[role="navigation"] a'
        )) {
            const lab = (a.getAttribute('aria-label') || a.getAttribute('title') || '').trim();
            if (!lab || !/нравится|likes?/i.test(lab)) continue;
            const m = lab.match(/([\\d][\\d\\s\\u00a0.,]*)\\s*(млрд|млн|тыс)?/i);
            if (m) {
                pageLikes = m[1].trim();
                if (m[2] && !/(млн|тыс|млрд)/i.test(pageLikes))
                    pageLikes += ' ' + m[2];
                break;
            }
        }
    }
    if (!pageLikes) {
        const banner = document.querySelector('[role="banner"]');
        if (banner) {
            const bt = (banner.innerText || '').replace(/\\u00a0/g, ' ');
            const m = bt.match(/([\\d][\\d\\s.,]*)\\s*(млрд|млн|тыс)?[^\\n]{0,12}нравится/iu);
            if (m) {
                pageLikes = m[1].trim().replace(/\\s+/g, ' ');
                if (m[2] && !/(млн|тыс|млрд)/i.test(pageLikes))
                    pageLikes += ' ' + m[2];
            }
        }
    }

    // ── Followers (подписчиков) ───────────────────────────────────────────────
    // Formats: "15 млн — подписчиков", "15M followers", "N people follow this".
    // Важный кейс: при 0 Facebook может не показывать слово "подписчик*".
    // Если ссылка followers найдена, но числа нет — это подтверждённый 0.
    let followers = '';
    let followersConfirmed = false;
    function parseCompactNum(text) {
        const t0 = (text || '').toString().replace(/[\\u00a0\\u202f]/g, ' ').trim();
        if (!t0) return NaN;
        const ru = t0.match(/^([\\d]+(?:[.,][\\d]+)?)\\s*(млрд|млн|тыс)\\.?/i);
        if (ru) {
            const n = parseFloat(ru[1].replace(',', '.'));
            const m = { млн: 1e6, тыс: 1e3, млрд: 1e9 }[ru[2].toLowerCase()] || 1;
            return Math.round(n * m);
        }
        const la = t0.replace(/\\s+/g, '').replace(',', '.').match(/^([\\d]+(?:\\.[\\d]+)?)([KkMmBb]?)$/);
        if (la) {
            const m = { K: 1e3, M: 1e6, B: 1e9 }[la[2].toUpperCase()] || 1;
            return Math.round(parseFloat(la[1]) * m);
        }
        const digits = t0.replace(/[^\\d]/g, '');
        return digits ? parseInt(digits, 10) : NaN;
    }
    function readFollowersFromLink(a) {
        if (!a) return { ok: false, value: 0 };
        const href = (a.getAttribute('href') || '').toLowerCase();
        if (!(href.includes('followers') || href.includes('sk=followers'))) {
            return { ok: false, value: 0 };
        }
        const chunks = [];
        const aria = (a.getAttribute('aria-label') || '').trim();
        const title = (a.getAttribute('title') || '').trim();
        const txt = (a.innerText || a.textContent || '').trim();
        if (aria) chunks.push(aria);
        if (title) chunks.push(title);
        if (txt) chunks.push(txt);
        const joined = chunks.join(' | ');
        const hasFollowerWord = /(подписчик|followers?|follow this)/i.test(joined);
        const labelled = joined.match(/([\\d][\\d\\s\\u00a0.,]*(?:\\s*(?:млрд|млн|тыс|[KkMmBb]))?)\\s*(?:подписчик\\w*|followers?|people\\s+follow\\s+this)/i);
        if (labelled) {
            const n = parseCompactNum(labelled[1]);
            if (Number.isFinite(n) && n >= 0) return { ok: true, value: n };
        }
        for (const node of a.querySelectorAll('strong, span')) {
            const t = (node.innerText || node.textContent || '').trim();
            if (!t) continue;
            const n = parseCompactNum(t);
            if (Number.isFinite(n) && n >= 0) return { ok: true, value: n };
        }
        const anyNum = joined.match(/([\\d][\\d\\s\\u00a0.,]*(?:\\s*(?:млрд|млн|тыс|[KkMmBb]))?)/i);
        if (anyNum) {
            const n = parseCompactNum(anyNum[1]);
            if (Number.isFinite(n) && n >= 0) return { ok: true, value: n };
        }
        if (hasFollowerWord || href.includes('sk=followers') || href.includes('/followers')) {
            return { ok: true, value: 0 };
        }
        return { ok: false, value: 0 };
    }
    const followerAnchors = document.querySelectorAll(
        '[role="banner"] a[href*="followers"], [role="banner"] a[href*="sk=followers"], ' +
        '[role="navigation"] a[href*="followers"], [role="navigation"] a[href*="sk=followers"], ' +
        '[role="main"] a[href*="followers"], [role="main"] a[href*="sk=followers"], ' +
        'a[href*="profile.php?id="][href*="sk=followers"]'
    );
    for (const a of followerAnchors) {
        const got = readFollowersFromLink(a);
        if (got.ok) {
            followers = String(got.value);
            followersConfirmed = true;
            break;
        }
    }
    if (!followersConfirmed) {
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
                followersConfirmed = true;
                break;
            }
        }
    }
    // Шапка / навигация: на вкладке «Фото» в body часто нет «X — подписчиков».
    if (!followersConfirmed) {
        const selF = '[role="banner"] a[href*="followers"],[role="banner"] a[href*="sk=followers"],' +
            '[role="navigation"] a[href*="followers"],[role="navigation"] a[href*="sk=followers"]';
        for (const a of document.querySelectorAll(selF)) {
            const lab = (a.getAttribute('aria-label') || a.getAttribute('title') || '').trim();
            if (!lab) continue;
            let m = lab.match(/([\\d][\\d\\s\\u00a0.,]*)\\s*(млрд|млн|тыс)?[^\\d\\w]{0,40}подписчик/i);
            if (!m) m = lab.match(/([\\d][\\d\\s.,]*)\\s*(?:[KkMmBb])?\\s*followers?/i);
            if (m) {
                followers = m[1].trim();
                if (m[2] && !/(млн|тыс|млрд)/i.test(followers))
                    followers += ' ' + m[2];
                followersConfirmed = true;
                break;
            }
        }
    }
    if (!followersConfirmed) {
        const banner = document.querySelector('[role="banner"]');
        if (banner) {
            const bt = (banner.innerText || '').replace(/\\u00a0/g, ' ');
            let m = bt.match(/([\\d][\\d\\s.,]*)\\s*(млрд|млн|тыс)?\\s*подписчик/iu);
            if (!m) m = bt.match(/([\\d][\\d\\s.,]*)\\s*(?:[KkMmBb])?\\s*followers?/i);
            if (m) {
                followers = m[1].trim().replace(/\\s+/g, ' ');
                if (m[2] && !/(млн|тыс|млрд)/i.test(followers))
                    followers += ' ' + m[2];
                followersConfirmed = true;
            }
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

    if (badDisplay(displayName)) displayName = '';

    return {
        displayName,
        avatar,
        bio,
        followers,
        followersConfirmed,
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

    function lblLooksLikeViews(lbl) {
        const low = (lbl || '').toLowerCase();
        return /просмотр|\\bviews?\\b|\\bwatch\\b|play count|воспроизвед|played|viewers/i.test(low);
    }

    /** Только явные подписи счётчика просмотров (не *=view — цепляется «overview» и т.п.). */
    function lblIsExplicitViewCount(lbl) {
        if (!lbl) return false;
        if (/просмотр/i.test(lbl)) return true;
        if (/\\bviews?\\b/i.test(lbl)) return true;
        if (/\\bwatch\\b|play count|просмотрено/i.test(lbl.toLowerCase())) return true;
        return false;
    }

    /** «16 тыс. просмотров», «1,2 млн просмотров», «734 просмотра» — между числом и словом может быть млн/тыс. */
    function parseViewsFromAriaLabel(lbl) {
        if (!lbl) return 0;
        let m = lbl.match(
            /([\\d][\\d\\s.,]*\\s*(?:млрд|млн|тыс)\\.?)\\s*(?:просмотр|views?|watch(?:es)?)/i
        );
        if (m) return parseNum(m[1].replace(/\\s+/g, ' ').trim());
        m = lbl.match(/([\\d][\\d\\s.,]*)\\s*(?:просмотр|views?|watch(?:es)?)/i);
        if (m) return parseNum(m[1].trim());
        m = lbl.match(/(?:views?|просмотр)\\s*[:\\-]?\\s*([\\d][\\d\\s.,]*\\s*(?:млрд|млн|тыс)\\.?)/i);
        if (m) return parseNum(m[1].replace(/\\s+/g, ' ').trim());
        m = lbl.match(/(?:views?|просмотр)\\s*[:\\-]?\\s*([\\d][\\d\\s.,]*)/i);
        if (m) return parseNum(m[1].trim());
        return 0;
    }

    /** Отдельно от getBtnCount: там lblLooksLikeViews() обнуляет корректные «11 views». */
    function getViewCountFromControl(el) {
        if (!el) return 0;
        const lbl = el.getAttribute('aria-label') || '';
        if (lbl) {
            const fromLbl = parseViewsFromAriaLabel(lbl);
            if (fromLbl > 0) return fromLbl;
        }
        for (const node of [...el.querySelectorAll('span,div')].reverse()) {
            if (node.children.length > 0) continue;
            const raw = (node.textContent || '').replace(/[\\u00a0\\u202f]/g, ' ').trim();
            if (/^[\\d]+(?:[.,][\\d]+)?\\s*(?:млрд|млн|тыс)\\.?$/i.test(raw)) {
                const v = parseNum(raw);
                if (v > 0) return v;
            }
            if (/^[\\d][\\d.,]*[KkMmBb]?$/.test(raw)) return parseNum(raw);
        }
        return 0;
    }

    function getBtnCount(btn) {
        if (!btn) return 0;
        const lbl = btn.getAttribute('aria-label') || '';
        if (lblLooksLikeViews(lbl)) return 0;
        const mL = lbl.match(/([\\d][\\d\\s,.]*)\\s*(?:reactions?|comments?|shares?|reacts?)/i);
        if (mL) return parseNum(mL[1]);
        // Нет цифры в подписи — у FB часто только иконка (0 лайков не пишут текстом).
        if (!/\\d/.test(lbl)) return 0;
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
            // Важно: для Reels в DOM часто есть и /posts/, и story_fbid — если взять их первыми,
            // id не совпадёт с сеткой sk=reels_tab (/reel/NUM) и merge не обнулит фантомные лайки (162).
            let postId = '', postUrl = '';
            const anchorSelectors = [
                'a[href*="/reel/"]',
                'a[href*="/videos/"]',
                'a[href*="/posts/"]',
                'a[href*="story_fbid"]',
                'a[href*="/permalink/"]',
                'a[href*="/photo/"]',
                'a[href*="fbid="]',
            ];
            outerId:
            for (const sel of anchorSelectors) {
                for (const a of art.querySelectorAll(sel)) {
                    const href = a.getAttribute('href') || '';
                    let m = href.match(/\\/reel\\/([\\w-]+)/);
                    if (!m) m = href.match(/\\/videos\\/([\\w-]+)/);
                    if (!m) m = href.match(/\\/posts\\/([\\w-]+)/);
                    if (!m) m = href.match(/story_fbid=([\\w-]+)/);
                    if (!m) m = href.match(/\\/permalink\\/([\\w-]+)/);
                    if (!m) m = href.match(/[?&]fbid=(\\d{8,})/);
                    if (m) {
                        postId = m[1];
                        postUrl = a.href || ('https://www.facebook.com' + href);
                        break outerId;
                    }
                }
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
            if (!thumb) {
                const svgIm = art.querySelector('svg image');
                if (svgIm) {
                    const h = (svgIm.getAttribute('href') || svgIm.getAttribute('xlink:href') || '').trim();
                    if (h && (h.includes('scontent') || h.includes('fbcdn')) &&
                        !h.includes('emoji.php')) thumb = h;
                }
            }

            // Reactions
            let reactions = 0;
            const reactBar = art.querySelector(
                '[aria-label*="reaction"],[aria-label*="React"],[aria-label*="реакц"]'
            );
            if (reactBar) {
                const rlab = reactBar.getAttribute('aria-label') || '';
                if (!lblLooksLikeViews(rlab)) reactions = getBtnCount(reactBar);
            }
            if (!reactions) {
                for (const btn of art.querySelectorAll('[role="button"]')) {
                    const rawLab = btn.getAttribute('aria-label') || '';
                    if (lblLooksLikeViews(rawLab)) continue;
                    const lbl = rawLab.toLowerCase();
                    if (lbl.includes('unlike') || (lbl.includes('убрать') && lbl.includes('нрав'))) continue;
                    if (lbl.includes('reaction') || lbl.includes('реакц') || lbl.includes('нравится') ||
                        /\\b(likes?|like)\\b/i.test(lbl)) {
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
                    const rawPl = p.getAttribute('aria-label') || '';
                    if (!/\\d/.test(rawPl)) continue;
                    const pl = rawPl.toLowerCase();
                    if (lblLooksLikeViews(rawPl)) continue;
                    if (pl.includes('unlike')) continue;
                    if (pl.includes('react') || pl.includes('реакц') || pl.includes('нравится') ||
                        /\\b(likes?|like)\\b/i.test(pl)) {
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

            // Views: getBtnCount() раньше возвращал 0 для «N views» из‑за lblLooksLikeViews →
            // срабатывал regex по всему innerText и бралось чужое большое число (часто у первого article).
            let views = 0;
            const viewCandidates = [];
            for (const el of art.querySelectorAll('[aria-label]')) {
                const lab = el.getAttribute('aria-label') || '';
                if (!lblIsExplicitViewCount(lab)) continue;
                const v = getViewCountFromControl(el);
                if (v > 0) viewCandidates.push(v);
            }
            if (viewCandidates.length === 1) views = viewCandidates[0];
            else if (viewCandidates.length > 1) views = Math.max.apply(null, viewCandidates);
            if (!views) {
                const txt = (art.innerText || '').replace(/\\r/g, '');
                const vals = [];
                const re =
                    /([\\d][\\d\\s,.]*(?:\\s*(?:млн|тыс|млрд)\\.?)?(?:[KkMmBb])?)\\s*(?:views?|просмотр)\\b/gi;
                let m;
                while ((m = re.exec(txt)) !== null) {
                    const val = parseNum(m[1].trim());
                    if (val > 0) vals.push(val);
                }
                if (vals.length === 1) views = vals[0];
                else if (vals.length > 1) views = Math.max.apply(null, vals);
            }

            if (reactions > 0 && views > 0 && reactions === views) reactions = 0;

            results.push({ id: postId, url: postUrl, text, ts, thumb,
                           reactions, comments, shares, views });
        } catch(_) {}
    }
    // Reels: одинаковое число «лайков» на карточках с разными просмотрами — артефакт UI.
    const reelPhantomReset = () => {
        const rows = results.filter(
            r => /\\/reel\\//i.test(r.url || '') && (Number(r.reactions) || 0) > 0
        );
        const by = new Map();
        for (const r of rows) {
            const k = Number(r.reactions) || 0;
            if (!by.has(k)) by.set(k, []);
            by.get(k).push(r);
        }
        for (const rowsK of by.values()) {
            if (rowsK.length < 3) continue;
            const k = Number(rowsK[0].reactions) || 0;
            if (k < 2) continue;
            const viewSet = new Set(rowsK.map(r => Number(r.views) || 0));
            if (viewSet.size < 3) continue;
            for (const r of rowsK) r.reactions = 0;
        }
    };
    reelPhantomReset();
    return results;
}"""


_SK_PHOTOS_REELS_JS = """(params) => {
    const maxPosts = Math.max(1, Number((params && params.maxPosts) || 80));
    const main = document.querySelector('[role="main"]') || document.body;
    const out = [];
    const seen = new Set();

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
    function parseViewsFromAriaLabel(lbl) {
        if (!lbl) return 0;
        let m = lbl.match(
            /([\\d][\\d\\s.,]*\\s*(?:млрд|млн|тыс)\\.?)\\s*(?:просмотр|views?|watch(?:es)?)/i
        );
        if (m) return parseNum(m[1].replace(/\\s+/g, ' ').trim());
        m = lbl.match(/([\\d][\\d\\s.,]*)\\s*(?:просмотр|views?|watch(?:es)?)/i);
        if (m) return parseNum(m[1].trim());
        m = lbl.match(/(?:views?|просмотр)\\s*[:\\-]?\\s*([\\d][\\d\\s.,]*\\s*(?:млрд|млн|тыс)\\.?)/i);
        if (m) return parseNum(m[1].replace(/\\s+/g, ' ').trim());
        m = lbl.match(/(?:views?|просмотр)\\s*[:\\-]?\\s*([\\d][\\d\\s.,]*)/i);
        if (m) return parseNum(m[1].trim());
        return 0;
    }

    function pickViews(root) {
        if (!root) return 0;
        for (const el of root.querySelectorAll('[aria-label]')) {
            const al = (el.getAttribute('aria-label') || '');
            const vAria = parseViewsFromAriaLabel(al);
            if (vAria > 0 && vAria < 1e10) return vAria;
        }
        const blob = (root.innerText || '').replace(/\\r/g, '');
        /** Оверлей сетки Reels: один span «16\\u00a0тыс.» без aria «просмотр». */
        const ruRe = /([\\d]+(?:[.,][\\d]+)?)\\s*(?:млрд|млн|тыс)\\.?/gi;
        const ruVals = [];
        let rm;
        while ((rm = ruRe.exec(blob)) !== null) {
            const v = parseNum(rm[0]);
            if (v > 0 && v < 1e11) ruVals.push(v);
        }
        if (ruVals.length === 1) return ruVals[0];
        if (ruVals.length > 1) return Math.max.apply(null, ruVals);
        const m2 = blob.match(
            /([\\d][\\d\\s,.]*(?:\\s*(?:млн|тыс|млрд)\\.?)?[KkMmBb]?)\\s*(?:просмотр|views?)/i
        );
        if (m2) {
            const v = parseNum(m2[1].trim());
            if (v > 0 && v < 1e10) return v;
        }
        for (const sp of root.querySelectorAll('span')) {
            const t0 = (sp.textContent || '').replace(/[\\u00a0\\u202f]/g, ' ').trim();
            if (/^[\\d]+(?:[.,][\\d]+)?\\s*(?:млрд|млн|тыс)\\.?$/i.test(t0)) {
                const vAb = parseNum(t0);
                if (vAb > 0 && vAb < 1e11) return vAb;
            }
        }
        for (const sp of root.querySelectorAll('span')) {
            const t = (sp.textContent || '').replace(/[\\u00a0\\u202f]/g, '').trim();
            if (!/^\\d{1,9}$/.test(t)) continue;
            let piece = t;
            let nx = sp.nextElementSibling;
            while (nx && nx.tagName === 'SPAN') {
                const u = (nx.textContent || '').trim();
                if (/^(млрд|млн|тыс)\\.?$/i.test(u) || /^[KkMmBb]$/i.test(u)) {
                    piece += ' ' + u;
                    nx = nx.nextElementSibling;
                    continue;
                }
                break;
            }
            const num = parseNum(piece);
            if (num < 1 || num >= 1e11) continue;
            let p = sp.parentElement;
            for (let d = 0; d < 4 && p; d++) {
                const al = (p.getAttribute && p.getAttribute('aria-label')) || '';
                if (/просмотр|view/i.test(al)) return num;
                p = p.parentElement;
            }
        }
        return 0;
    }

    function parseLikesFromAriaLabel(lbl) {
        if (!lbl) return 0;
        if (/просмотр|\\bviews?\\b|\\bwatch\\b|play count|воспроизвед/i.test(lbl)) return 0;
        let m = lbl.match(
            /([\\d][\\d\\s.,]*\\s*(?:млрд|млн|тыс)\\.?)\\s*(?:reactions?|likes?|лайк|нравится|отметок)/i
        );
        if (m) return parseNum(m[1].replace(/\\s+/g, ' ').trim());
        m = lbl.match(/([\\d][\\d\\s.,]*)\\s*(?:reactions?|likes?|лайк|нравится|отметок)/i);
        if (m) return parseNum(m[1].trim());
        m = lbl.match(
            /(?:reactions?|likes?|лайк|нравится)\\s*[:\\-]?\\s*([\\d][\\d\\s.,]*\\s*(?:млрд|млн|тыс)\\.?)/i
        );
        if (m) return parseNum(m[1].replace(/\\s+/g, ' ').trim());
        m = lbl.match(/(?:reactions?|likes?|лайк|нравится)\\s*[:\\-]?\\s*([\\d][\\d\\s.,]*)/i);
        if (m) return parseNum(m[1].trim());
        return 0;
    }

    /** Лайки/реакции на карточке сетки Reels (рядом с просмотрами, отдельный span). */
    function pickLikes(root) {
        if (!root) return 0;
        for (const el of root.querySelectorAll('[aria-label]')) {
            const al = (el.getAttribute('aria-label') || '');
            const n = parseLikesFromAriaLabel(al);
            if (n > 0 && n < 1e10) return n;
        }
        const blob = (root.innerText || '').replace(/\\r/g, '');
        const lines = blob.split(/[\\n\\r]+/).map((s) => s.trim()).filter(Boolean);
        for (const line of lines) {
            if (/просмотр|\\bviews?\\b|watch/i.test(line)) continue;
            const m = line.match(
                /^([\\d][\\d\\s.,]*(?:\\s*(?:млрд|млн|тыс)\\.?)?)\\s*(?:нравится|likes?|reactions?|лайк)\\b\\.?$/i
            );
            if (m) {
                const n = parseNum(m[1].trim());
                if (n > 0 && n < 1e10) return n;
            }
        }
        const likeRe =
            /([\\d]+(?:[.,][\\d]+)?(?:\\s*(?:млрд|млн|тыс)\\.?)?)\\s*(?:нравится|likes?|reactions?)\\b/gi;
        const vals = [];
        let lm;
        while ((lm = likeRe.exec(blob)) !== null) {
            const n = parseNum(lm[1].trim());
            if (n > 0 && n < 1e10) vals.push(n);
        }
        if (vals.length === 1) return vals[0];
        if (vals.length > 1) return Math.max.apply(null, vals);
        for (const sp of root.querySelectorAll('span')) {
            const t0 = (sp.textContent || '').replace(/[\\u00a0\\u202f]/g, ' ').trim();
            if (!/^[\\d]{1,9}$/.test(t0)) continue;
            let p = sp.parentElement;
            for (let d = 0; d < 5 && p; d++) {
                const al = (p.getAttribute && p.getAttribute('aria-label')) || '';
                if (!al) {
                    p = p.parentElement;
                    continue;
                }
                if (/просмотр|\\bviews?\\b/i.test(al)) {
                    p = p.parentElement;
                    continue;
                }
                if (/нравится|reaction|\\blike\\b|лайк/i.test(al)) return parseNum(t0);
                p = p.parentElement;
            }
        }
        return 0;
    }

    for (const a of main.querySelectorAll('a[href*="/reel/"]')) {
        const href = a.getAttribute('href') || '';
        const m = href.match(/\\/reel\\/(\\d+)/);
        if (!m) continue;
        const id = m[1];
        if (seen.has(id)) continue;
        seen.add(id);
        let card = a.closest('[role="article"]');
        if (!card) {
            let p = a.parentElement;
            for (let d = 0; d < 10 && p; d++) {
                if (p.querySelector && p.querySelectorAll('img').length >= 1) {
                    card = p;
                    break;
                }
                p = p.parentElement;
            }
        }
        if (!card) card = a.parentElement;
        const views = pickViews(card || a);
        const likes = pickLikes(card || a);
        let thumb = '';
        for (const im of (card || a).querySelectorAll('img')) {
            const s = im.getAttribute('src') || '';
            if (s && (s.includes('scontent') || s.includes('fbcdn')) && !s.includes('emoji.php')) {
                thumb = s;
                break;
            }
        }
        if (!thumb) {
            const si = (card || a).querySelector('svg image');
            if (si) {
                const h = (si.getAttribute('href') || si.getAttribute('xlink:href') || '').trim();
                if (h && (h.includes('scontent') || h.includes('fbcdn'))) thumb = h;
            }
        }
        out.push({
            id,
            url: a.href || href,
            text: '',
            ts: '',
            thumb,
            reactions: likes,
            comments: 0,
            shares: 0,
            views,
        });
        if (out.length >= maxPosts) break;
    }
    return out;
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


def _merge_facebook_post_rows(primary: list, sk_reels: list) -> list:
    """Объединить посты из [role=article] и сетки Reels на sk=reels_tab (просмотры)."""
    by_id: dict[str, dict] = {}
    for p in primary or []:
        rid = str(p.get("id") or "").strip()
        if rid:
            by_id[rid] = dict(p)
    for row in sk_reels or []:
        rid = str(row.get("id") or "").strip()
        if not rid:
            continue
        if rid not in by_id:
            by_id[rid] = dict(row)
            continue
        ex = by_id[rid]
        rv = int(row.get("views") or 0)
        if rv > int(ex.get("views") or 0):
            ex["views"] = row.get("views", 0)
        sk_r = int(row.get("reactions") or 0)
        ex_r = int(ex.get("reactions") or 0)
        if sk_r > ex_r:
            ex["reactions"] = row.get("reactions", 0)
        # Просмотры/превью с сетки; лайки — max(article, сетка pickLikes), затем enrich и анти-артефакты.
        t = row.get("thumb") or ""
        if t and (not ex.get("thumb") or len(str(t)) > len(str(ex.get("thumb") or ""))):
            ex["thumb"] = t
        u = row.get("url") or ""
        if u and "/reel/" in str(u):
            ex["url"] = u
    return list(by_id.values())


def _merge_facebook_profile_js(timeline: dict, photos: dict | None) -> dict:
    """
    Слияние снимка профиля до и после ``sk=reels_tab``: подписчики/лайки с основной
    страницы, аватар и отладка со страницы Reels приоритетнее, если качество выше.
    """
    t = dict(timeline or {})
    if not photos:
        return t
    p = dict(photos or {})

    fb_t = _parse_count(str(t.get("followers") or ""))
    fb_p = _parse_count(str(p.get("followers") or ""))
    fc_t = bool(t.get("followersConfirmed"))
    fc_p = bool(p.get("followersConfirmed"))
    if fc_t and not fc_p:
        merged_followers = (t.get("followers") or "").strip()
        merged_followers_confirmed = True
    elif fc_p and not fc_t:
        merged_followers = (p.get("followers") or "").strip()
        merged_followers_confirmed = True
    else:
        merged_followers = (p.get("followers") or "").strip() if fb_p > fb_t else (t.get("followers") or "").strip()
        merged_followers_confirmed = fc_t or fc_p

    pl_t = _parse_count(str(t.get("pageLikes") or ""))
    pl_p = _parse_count(str(p.get("pageLikes") or ""))
    merged_likes = (p.get("pageLikes") or "").strip() if pl_p > pl_t else (t.get("pageLikes") or "").strip()

    dn_t = sanitize_facebook_display_name(t.get("displayName"))
    dn_p = sanitize_facebook_display_name(p.get("displayName"))
    merged_name = dn_p or dn_t

    av_t = (t.get("avatar") or "").strip()
    av_p = (p.get("avatar") or "").strip()

    def av_score(u: str) -> int:
        if not u or "emoji.php" in u:
            return 0
        sc = min(len(u) // 15, 40)
        if "scontent" in u or "fbcdn" in u:
            sc += 40
        if "s200x200" in u or "p200x200" in u or "s720x" in u or "s960x" in u:
            sc += 20
        return sc

    if not is_usable_facebook_avatar_url(av_p):
        av_p = ""
    if not is_usable_facebook_avatar_url(av_t):
        av_t = ""
    merged_avatar = av_p if av_score(av_p) >= av_score(av_t) else av_t

    bio_t = (t.get("bio") or "").strip()
    bio_p = (p.get("bio") or "").strip()
    merged_bio = bio_p if len(bio_p) > len(bio_t) else bio_t

    dbg_tl = (t.get("dbg") or "")[:140]
    dbg_ph = (p.get("dbg") or "")[:140]
    merged_dbg = (dbg_ph + " |TL " + dbg_tl)[:300]

    return {
        "displayName": merged_name,
        "avatar": merged_avatar,
        "bio": merged_bio,
        "followers": merged_followers,
        "followersConfirmed": merged_followers_confirmed,
        "pageLikes": merged_likes,
        "dbg": merged_dbg,
        "dbgLikes": (p.get("dbgLikes") or t.get("dbgLikes") or ""),
        "likeDbg": (p.get("likeDbg") or t.get("likeDbg") or []),
        "nravLines": list(t.get("nravLines") or []) + list(p.get("nravLines") or []),
    }


async def _facebook_ensure_reels_sk_page(page, reels_sk_url: str | None) -> None:
    """Если ушли со страницы ``sk=reels_tab``, вернуться по сохранённому URL (иначе клики по сетке ломаются)."""
    if not (reels_sk_url or "").strip():
        return
    u = (page.url or "").lower()
    if "sk=reels_tab" in u or "sk%3dreels_tab" in u:
        return
    try:
        print("[facebook_worker] возврат на sk=reels_tab перед Reel", file=sys.stderr)
        await page.goto(reels_sk_url.strip(), wait_until="domcontentloaded", timeout=NAV_TIMEOUT)
        await page.wait_for_timeout(1200)
    except Exception as exc:
        print(f"[facebook_worker] sk=reels_tab restore: {exc}", file=sys.stderr)


async def _fb_xpath_like_text(page, xpath: str) -> str:
    try:
        return str(await page.evaluate(_FB_XPATH_LIKE_TEXT_JS, xpath) or "").strip()
    except Exception:
        return ""


async def _fb_like_count_from_aria_labels(page) -> int:
    """
    В модалке Reels счётчик часто только в ``aria-label`` (в т.ч. «у 9 пользователей»),
    а ``_FB_FALLBACK_LIKES_TEXT_JS`` / XPath дают 0 — тот же обход, что в same-tab.
    """
    n = 0
    try:
        loc = page.locator(
            '[role="dialog"] [aria-label*="нравится" i], [role="dialog"] [aria-label*="like" i], '
            '[role="dialog"] [aria-label*="reaction" i], '
            '[role="main"] [aria-label*="нравится" i], [role="main"] [aria-label*="like" i], '
            '[role="main"] [aria-label*="reaction" i]'
        )
        cnt = await loc.count()
        for i in range(min(cnt, 45)):
            try:
                lab_s = str(await loc.nth(i).get_attribute("aria-label", timeout=1200) or "")
                if _fb_aria_label_looks_like_views(lab_s):
                    continue
                parsed = max(_parse_count(lab_s), _parse_like_count_from_aria_label(lab_s))
                if parsed > n:
                    n = parsed
            except Exception:
                continue
    except Exception:
        pass
    return n


async def _fb_dom_like_read(page, xpath: str) -> tuple[int, bool]:
    """
    Лайки с открытого Reel / модалки.

    ``confirmed=True`` — найдена видимая кнопка «Нравится»; отсутствие цифры = 0 лайков.
    """
    try:
        vis = await page.evaluate(_FB_VISIBLE_REEL_LIKE_JS)
        if isinstance(vis, dict) and vis.get("found"):
            return int(vis.get("digit") or 0), True
    except Exception:
        pass
    try:
        fb = str(await page.evaluate(_FB_FALLBACK_LIKES_TEXT_JS) or "").strip()
        if fb:
            return _parse_count(fb), False
    except Exception:
        pass
    raw = await _fb_xpath_like_text(page, xpath)
    n_x = _parse_count(raw)
    if n_x > 0:
        return n_x, False
    n_a = await _fb_like_count_from_aria_labels(page)
    if n_a > 0:
        return n_a, False
    return 0, False


async def _fb_dom_like_text_combined(page, xpath: str) -> int:
    """Обратная совместимость: только число лайков без флага подтверждения."""
    likes, _confirmed = await _fb_dom_like_read(page, xpath)
    return likes


def _facebook_detail_likes_should_apply(likes: int, prev: int, vcount: int, *, confirmed: bool) -> bool:
    if confirmed:
        return True
    if likes <= 0:
        return False
    if likes > prev:
        return True
    if prev > 0 and vcount > 0 and prev >= vcount and likes < prev:
        return True
    return False


async def _facebook_try_reel_likes_modal(
    page, reel_id: str, xpath: str, reels_sk_url: str | None = None
) -> tuple[int, bool]:
    """Клик по карточке ролика на текущей странице (не только ``/reel/`` в href)."""
    selectors = (
        f'[role="main"] a[href*="/reel/{reel_id}"]',
        f'[role="main"] a[href*="/posts/{reel_id}"]',
        f'[role="main"] a[href*="/videos/{reel_id}"]',
        f'[role="main"] a[href*="story_fbid={reel_id}"]',
        f'[role="main"] a[href*="story_fbid%3D{reel_id}"]',
    )
    last_exc: Exception | None = None
    try:
        pre_click = int(os.getenv("FACEBOOK_DETAIL_LIKES_PRE_CLICK_MS", "350") or "350")
        wait_ms = int(os.getenv("FACEBOOK_DETAIL_LIKES_MODAL_WAIT_MS", "3800") or "3800")
        for sel in selectors:
            try:
                link = page.locator(sel).first
                await link.scroll_into_view_if_needed(timeout=6000)
                await page.wait_for_timeout(max(0, min(3000, pre_click)))
                await link.click(timeout=12_000, force=True)
                try:
                    await page.wait_for_selector(
                        '[role="dialog"],[aria-modal="true"],[role="main"] video',
                        timeout=9000,
                    )
                except Exception:
                    pass
                try:
                    await page.locator("[role='main'] video").first.wait_for(state="attached", timeout=5000)
                except Exception:
                    pass
                await page.wait_for_timeout(max(1000, min(10_000, wait_ms)))
                likes, confirmed = await _fb_dom_like_read(page, xpath)
                return likes, confirmed
            except Exception as exc:
                last_exc = exc
                continue
        if last_exc:
            print(
                f"[facebook_worker] modal likes reel={reel_id}: все селекторы не сработали: {last_exc}",
                file=sys.stderr,
            )
        return 0, False
    finally:
        for _ in range(3):
            try:
                await page.keyboard.press("Escape")
                await page.wait_for_timeout(280)
            except Exception:
                break
        if reels_sk_url:
            u = (page.url or "").lower()
            if "sk=reels_tab" not in u and "sk%3dreels_tab" not in u:
                try:
                    await page.goto(reels_sk_url.strip(), wait_until="domcontentloaded", timeout=NAV_TIMEOUT)
                    await page.wait_for_timeout(900)
                except Exception as exc:
                    print(f"[facebook_worker] sk=reels_tab после модалки: {exc}", file=sys.stderr)


async def _facebook_try_reel_likes_same_tab(
    page, reel_url: str, xpath: str, reels_sk_url: str | None
) -> tuple[int, bool]:
    """Та же вкладка: открыть Reel по URL, прочитать лайки, вернуться на sk=reels_tab."""
    restore = (reels_sk_url or "").strip()
    if not restore:
        print(
            "[facebook_worker] same-tab likes: пропуск — нет URL вкладки Reels для возврата после просмотра",
            file=sys.stderr,
        )
        return 0, False
    n = 0
    confirmed = False
    try:
        await page.goto(reel_url, wait_until="domcontentloaded", timeout=28_000)
        try:
            await page.locator("[role='main'] video, video").first.wait_for(state="attached", timeout=8000)
        except Exception:
            pass
        wait_ms = int(os.getenv("FACEBOOK_DETAIL_LIKES_PAGE_WAIT_MS", "5500") or "5500")
        await page.wait_for_timeout(max(800, min(12_000, wait_ms)))
        n, confirmed = await _fb_dom_like_read(page, xpath)
        if confirmed:
            return n, True
        if n > 0:
            return n, False
        try:
            lab = await page.locator('[aria-label*="нравится" i], [aria-label*="like" i]').first.get_attribute(
                "aria-label", timeout=4000
            )
            lab_s = str(lab or "")
            if not _fb_aria_label_looks_like_views(lab_s):
                n = max(n, _parse_count(lab_s), _parse_like_count_from_aria_label(lab_s))
        except Exception:
            pass
        if n <= 0:
            try:
                print(
                    "[facebook_worker] same-tab likes: 0 после открытия Reel "
                    f"title={(await page.title())!r} url={(page.url or '')[:140]!r}",
                    file=sys.stderr,
                )
            except Exception:
                pass
        return n, confirmed
    except Exception as exc:
        print(f"[facebook_worker] same-tab likes {reel_url[:72]}…: {exc}", file=sys.stderr)
        return 0, False
    finally:
        try:
            await page.goto(restore, wait_until="domcontentloaded", timeout=NAV_TIMEOUT)
            await page.wait_for_timeout(900)
        except Exception as exc:
            print(f"[facebook_worker] same-tab restore sk=reels_tab: {exc}", file=sys.stderr)


async def _facebook_enrich_reel_likes_from_detail(
    page,
    posts: list[dict],
    *,
    reels_sk_url: str | None = None,
) -> int:
    """
    Ровно одно открытие на кандидата: на сетке Reels — клик по карточке (модалка); иначе —
    один ``goto`` на URL Reel. Лайки: XPath + эвристики по aria/тексту.

    Кандидаты: по умолчанию только ``view_count > FACEBOOK_DETAIL_LIKES_MIN_VIEWS`` (строго выше
    порога — без открытия всех роликов с малыми просмотрами). Плюс низкие Reels, если включено
    ``FACEBOOK_DETAIL_ENRICH_LOW_VIEW_REELS=1``.

    После чтения detail: значение применяется не только при ``likes > prev``, но и когда сетка
    явно спутала лайки с просмотрами (``prev >= vcount``), иначе корректные малые лайки (напр. 9)
    не записываются при ``prev`` ≈ 16k.
    """
    if not _facebook_detail_likes_enabled() or not posts:
        return 0
    min_v = _facebook_detail_likes_min_views()
    max_op = int(os.getenv("FACEBOOK_DETAIL_LIKES_MAX_OPENS", "30") or "30")
    max_op = max(1, min(50, max_op))
    xpath = (os.getenv("FACEBOOK_POST_LIKES_XPATH") or "").strip() or _DEFAULT_FB_REEL_LIKES_XPATH

    try_modal = bool(reels_sk_url) and "mbasic" not in (page.url or "").lower()

    enrich_low = _facebook_detail_enrich_low_view_reels()
    candidates: list[dict] = []
    for p in posts:
        try:
            v = int(p.get("view_count") or 0)
        except (TypeError, ValueError):
            v = 0
        rid = _facebook_reel_numeric_id_for_enrich(p)
        is_reel = bool(rid)
        if min_v > 0:
            if v > min_v or (enrich_low and is_reel and v <= min_v):
                candidates.append(p)
        elif v > 0:
            candidates.append(p)
    # Сначала те, у кого сетка дала ненулевые сомнительные лайки (чаще фантом), затем по просмотрам.
    candidates.sort(
        key=lambda x: (
            int(x.get("like_count") or 0) == 0,
            -int(x.get("view_count") or 0),
        ),
    )
    candidates = candidates[:max_op]

    improved = 0
    for p in candidates:
        reel_id = _facebook_reel_numeric_id_for_enrich(p)
        if not reel_id:
            continue
        open_url = _facebook_url_for_reel_enrich(p, reel_id)
        prev = int(p.get("like_count") or 0)
        vcount = int(p.get("view_count") or 0)
        likes = 0
        confirmed = False
        await _facebook_ensure_reels_sk_page(page, reels_sk_url)
        if try_modal:
            print(
                f"[facebook_worker] enrich reel: id={reel_id} views={vcount} (один раз: клик по карточке)",
                file=sys.stderr,
            )
            likes, confirmed = await _facebook_try_reel_likes_modal(page, reel_id, xpath, reels_sk_url)
        else:
            print(
                f"[facebook_worker] enrich reel: id={reel_id} views={vcount} (один раз: открытие по URL)",
                file=sys.stderr,
            )
            likes, confirmed = await _facebook_try_reel_likes_same_tab(page, open_url, xpath, reels_sk_url)

        if not _facebook_detail_likes_should_apply(likes, prev, vcount, confirmed=confirmed):
            await asyncio.sleep(_ms_jitter(350, 900))
            continue
        if not confirmed:
            if prev == 0 and vcount > 0 and likes >= vcount:
                print(
                    f"[facebook_worker] detail likes: пропуск likes>=views при prev=0 ({likes}/{vcount}) "
                    f"reel={reel_id}",
                    file=sys.stderr,
                )
                await asyncio.sleep(_ms_jitter(350, 900))
                continue
            if vcount > 0 and likes == vcount and prev > 0 and not (prev >= vcount and likes < prev):
                print(
                    f"[facebook_worker] detail likes: пропуск like==views ({likes}) reel={reel_id}",
                    file=sys.stderr,
                )
                await asyncio.sleep(_ms_jitter(350, 900))
                continue
        p["like_count"] = likes
        if confirmed:
            p["like_count_confirmed"] = True
        improved += 1
        tag = "confirmed" if confirmed else "heuristic"
        print(
            f"[facebook_worker] detail likes reel={reel_id}: {likes} ({tag}, min_views={min_v}, prev={prev})",
            file=sys.stderr,
        )
        await asyncio.sleep(_ms_jitter(350, 900))

    return improved


async def _extract_mbasic_fallback(page, mbasic_timeline_url: str, *, profile_label: str) -> dict:
    """Fallback для Facebook: более простой HTML на mbasic."""
    try:
        await asyncio.sleep(_ms_jitter(PAUSE_PRE_M_BASIC_MIN_MS, PAUSE_PRE_M_BASIC_MAX_MS))
        await page.goto(
            mbasic_timeline_url,
            wait_until="domcontentloaded",
            timeout=NAV_TIMEOUT,
        )
        await page.wait_for_timeout(1800)
        data = await page.evaluate(
            _MBASIC_FALLBACK_JS, {"username": profile_label, "maxPosts": MAX_POSTS}
        )
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

def _facebook_reels_sk_url_from_nav(nav_url: str) -> str:
    """Стабильный URL вкладки Reels (``sk=reels_tab``) без повторного клика по UI."""
    u = (nav_url or "").strip().split("#", 1)[0].rstrip("/")
    if not u:
        return ""
    low = u.lower()
    if "sk=reels_tab" in low or "sk%3dreels_tab" in low:
        return u
    sep = "&" if "?" in u else "?"
    return f"{u}{sep}sk=reels_tab"


def _facebook_page_on_reels_sk(url: str | None) -> bool:
    u = (url or "").lower()
    return "sk=reels_tab" in u or "sk%3dreels_tab" in u


def _facebook_reels_ui_click_fallback_enabled() -> bool:
    for key in ("FACEBOOK_REELS_UI_CLICK_FALLBACK", "FACEBOOK_PHOTOS_UI_CLICK_FALLBACK"):
        if os.getenv(key, "").strip().lower() in {"1", "true", "yes", "on"}:
            return True
    return False


def _load_worker_utils():
    import importlib.util as _ilu
    _wu_path = Path(__file__).parent.parent / "worker_utils.py"
    if not _wu_path.exists():
        raise RuntimeError("Внутренняя ошибка: worker_utils.py не найден.")
    _wu_spec = _ilu.spec_from_file_location("worker_utils", _wu_path)
    _wu = _ilu.module_from_spec(_wu_spec)
    _wu_spec.loader.exec_module(_wu)
    return _wu


async def _facebook_open_reels_sk_tab_ui(page) -> bool:
    """
    Клик по вкладке/ссылке Reels до появления ``sk=reels_tab`` в URL.

    Основной путь — второй ``page.goto`` на URL с ``sk=reels_tab``; эта функция
    используется только при ``FACEBOOK_REELS_UI_CLICK_FALLBACK=1`` (или legacy
    ``FACEBOOK_PHOTOS_UI_CLICK_FALLBACK``), если прямой ``goto`` не дал ``sk=reels_tab``.
    """
    url = page.url or ""
    if _facebook_page_on_reels_sk(url):
        return True

    selectors = (
        'div[role="tablist"] a[href*="sk=reels_tab"], div[role="tablist"] a[href*="sk%3Dreels_tab"]',
        '[role="navigation"] a[href*="sk=reels_tab"], [role="navigation"] a[href*="sk%3Dreels_tab"]',
        '[role="banner"] a[href*="sk=reels_tab"], [role="banner"] a[href*="sk%3Dreels_tab"]',
        'a[href*="sk=reels_tab"], a[href*="sk%3Dreels_tab"]',
    )
    clicked = False
    for sel in selectors:
        try:
            loc = page.locator(sel).first
            await loc.wait_for(state="visible", timeout=5_000)
            await loc.click(timeout=8_000)
            clicked = True
            break
        except Exception:
            continue

    if not clicked:
        try:
            tab = page.get_by_role("tab", name=re.compile(r"reels|ролик|видео", re.I)).first
            await tab.wait_for(state="visible", timeout=6_000)
            await tab.click(timeout=8_000)
            clicked = True
        except Exception:
            return False

    try:
        await page.wait_for_function(
            """() => {
                const h = (location.href || '').toLowerCase();
                const s = (location.search || '').toLowerCase();
                return s.includes('sk=reels_tab') || h.includes('sk=reels_tab') ||
                    h.includes('sk%3dreels_tab');
            }""",
            timeout=15_000,
        )
    except Exception:
        await page.wait_for_timeout(2500)

    u = page.url or ""
    return _facebook_page_on_reels_sk(u)


async def _run_with_page(username: str, page, _wu):
    network_post_metrics: dict[str, dict] = {}

    async def _on_response(resp):
        await _capture_response_post_metrics(resp, network_post_metrics)

    def _on_response_sync(resp):
        asyncio.create_task(_on_response(resp))

    page.on("response", _on_response_sync)
    try:
        return await _run_with_page_core(
            username, page, _wu, network_post_metrics
        )
    finally:
        try:
            page.remove_listener("response", _on_response_sync)
        except Exception:
            pass


async def _run_with_page_core(
    username_raw: str,
    page,
    _wu,
    network_post_metrics: dict[str, dict],
):
    try:
        nav_url, mbasic_url, post_base = normalize_facebook_profile_input(username_raw)
    except ValueError as exc:
        raise ValueError(str(exc)) from exc

    # ── 1. Navigate ───────────────────────────────────────────────
    print(f"[facebook_worker] navigating to {nav_url}", file=sys.stderr)
    await asyncio.sleep(_ms_jitter(PAUSE_PRE_NAV_MIN_MS, PAUSE_PRE_NAV_MAX_MS))
    await page.goto(
        nav_url,
        wait_until="domcontentloaded",
        timeout=NAV_TIMEOUT,
    )
    await _wu.wait_for_anti_bot_clear(page, platform="facebook")
    await _facebook_raise_if_rate_limited(page, stage="профиль")

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

    # Снимок с основной страницы до Reels — подписчики / «Нравится» часто только здесь.
    info_timeline = await page.evaluate(_PROFILE_JS, username_raw)
    print(
        f"[facebook_worker] до Reels (sk=reels_tab): followers_raw={info_timeline.get('followers')!r} "
        f"pageLikes_raw={info_timeline.get('pageLikes')!r}",
        file=sys.stderr,
    )

    # ── 3b. Reels (sk=reels_tab) — второй и последний навигационный переход на www в этом проходе.
    reels_sk_nav = _facebook_reels_sk_url_from_nav(nav_url)
    print(f"[facebook_worker] navigating to Reels (sk=reels_tab): {reels_sk_nav}", file=sys.stderr)
    await asyncio.sleep(_ms_jitter(PAUSE_PRE_NAV_MIN_MS, PAUSE_PRE_NAV_MAX_MS))
    await page.goto(
        reels_sk_nav,
        wait_until="domcontentloaded",
        timeout=NAV_TIMEOUT,
    )
    await _wu.wait_for_anti_bot_clear(page, platform="facebook")
    await _facebook_raise_if_rate_limited(page, stage="reels")
    await page.wait_for_timeout(2000)
    on_reels_sk = _facebook_page_on_reels_sk(page.url)
    if not on_reels_sk and _facebook_reels_ui_click_fallback_enabled():
        print(
            "[facebook_worker] после goto нет sk=reels_tab в URL — пробуем клик по вкладке Reels "
            "(FACEBOOK_REELS_UI_CLICK_FALLBACK / FACEBOOK_PHOTOS_UI_CLICK_FALLBACK)",
            file=sys.stderr,
        )
        on_reels_sk = await _facebook_open_reels_sk_tab_ui(page)
    if on_reels_sk:
        print("[facebook_worker] страница Reels (sk=reels_tab) открыта", file=sys.stderr)
        await page.wait_for_timeout(2000)
        info_reels = await page.evaluate(_PROFILE_JS, username_raw)
        info = _merge_facebook_profile_js(info_timeline, info_reels)
        print(
            f"[facebook_worker] после merge профиля: followers_raw={info.get('followers')!r} "
            f"pageLikes_raw={info.get('pageLikes')!r}",
            file=sys.stderr,
        )
    else:
        print(
            "[facebook_worker] sk=reels_tab не подтверждён в URL — парсим как есть (без merge сетки Reels)",
            file=sys.stderr,
        )
        info = info_timeline

    # Сохранение URL sk=reels_tab для enrich (модалка / goto Reel и возврат).
    reels_sk_url_saved: str | None = None
    if on_reels_sk:
        u_sk = (page.url or "").lower()
        if "sk=reels_tab" in u_sk or "sk%3dreels_tab" in u_sk:
            reels_sk_url_saved = page.url
        else:
            reels_sk_url_saved = _facebook_reels_sk_url_from_nav(nav_url) or None

    # ── 4. Profile data (уже в info) ───────────────────────────────

    dn_raw = sanitize_facebook_display_name(info.get("displayName"))
    display_name   = dn_raw or username_raw
    follower_count = _parse_count(info.get("followers") or "")
    like_count_val = _parse_count(info.get("pageLikes") or "")
    avatar_url     = info.get("avatar") or ""
    if not is_usable_facebook_avatar_url(avatar_url):
        avatar_url = ""
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

    # ── 5. Scroll — подгрузка ленты (больше итераций + scrollBy) ─────────────
    scroll_rounds = int(os.getenv("FACEBOOK_SCROLL_ROUNDS", "14") or "14")
    scroll_rounds = max(5, min(40, scroll_rounds))
    for i in range(scroll_rounds):
        n = await page.evaluate("""() => {
            const sel = '[role="main"] a[href*="/posts/"],' +
                '[role="main"] a[href*="story_fbid"],' +
                '[role="main"] a[href*="/videos/"],' +
                '[role="main"] a[href*="/reel/"],' +
                '[role="main"] a[href*="/permalink/"],' +
                '[role="main"] a[href*="/photo/"],' +
                '[role="main"] a[href*="fbid="],' +
                '[role="article"] a[href*="/reel/"]';
            return document.querySelectorAll(sel).length;
        }""")
        print(f"[facebook_worker] scroll {i}: {n} post-links visible", file=sys.stderr)
        if n >= MAX_POSTS:
            break
        await page.keyboard.press("End")
        try:
            await page.evaluate(
                "() => { window.scrollBy(0, Math.min(2800, "
                "Math.max(400, document.body.scrollHeight - window.scrollY - window.innerHeight))); }"
            )
        except Exception:
            pass
        await asyncio.sleep(_ms_jitter(PAUSE_SCROLL_MIN_MS, PAUSE_SCROLL_MAX_MS))
        await page.wait_for_timeout(650)
    await page.wait_for_timeout(1200)

    # ── 6. Extract posts ──────────────────────────────────────────
    posts_raw = await page.evaluate(_POSTS_JS, {"username": username_raw, "maxPosts": MAX_POSTS})

    if on_reels_sk or _facebook_page_on_reels_sk(page.url):
        try:
            sk_reels = await page.evaluate(_SK_PHOTOS_REELS_JS, {"maxPosts": MAX_POSTS})
        except Exception as e:
            print(f"[facebook_worker] sk=reels_tab reels extract: {e}", file=sys.stderr)
            sk_reels = []
        if isinstance(sk_reels, list) and sk_reels:
            posts_raw = _merge_facebook_post_rows(posts_raw, sk_reels)
            print(
                f"[facebook_worker] Reels (sk=reels_tab): после merge {len(posts_raw)} пост(ов)",
                file=sys.stderr,
            )

    # ── 7. Fallback на mbasic — только если не на www sk=reels_tab (иначе лишний уход с Reels).
    u_after = (page.url or "").lower()
    on_www_reels_sk = _facebook_page_on_reels_sk(page.url) and "mbasic." not in u_after

    mbasic_data = {"followers": "", "pageLikes": "", "posts": []}
    need_mbasic = (len(posts_raw) < 3) or (follower_count <= 0)
    if _facebook_mbasic_fallback_enabled() and need_mbasic:
        if on_www_reels_sk:
            print(
                "[facebook_worker] mbasic пропуск: уже на www Reels (sk=reels_tab), "
                "без перехода на mbasic/timeline за подписчиками.",
                file=sys.stderr,
            )
        else:
            mbasic_data = await _extract_mbasic_fallback(
                page, mbasic_url, profile_label=username_raw
            )
            fb_fallback = _parse_count(mbasic_data.get("followers", ""))
            likes_fallback = _parse_count(mbasic_data.get("pageLikes", ""))
            if fb_fallback > follower_count:
                follower_count = fb_fallback
            if likes_fallback > like_count_val:
                like_count_val = likes_fallback
            existing_ids = {str(p.get("id", "")).strip() for p in posts_raw if p.get("id")}
            for row in (mbasic_data.get("posts") or []):
                rid = str(row.get("id", "")).strip()
                if rid and rid not in existing_ids:
                    posts_raw.append(row)
                    existing_ids.add(rid)
    elif need_mbasic:
        print(
            "[facebook_worker] mbasic fallback выключен — остаёмся на текущей странице. "
            "Для включения: FACEBOOK_MBASIC_FALLBACK=1",
            file=sys.stderr,
        )

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
        raw_url = nmeta.get("post_url") or p.get("url", f"{post_base}/posts/{post_id}")
        post_url_final = str(raw_url or "").strip()
        dom_likes = _parse_count(p.get("reactions", 0))
        dom_views = _parse_count(p.get("views", 0))
        net_views = int(nmeta.get("views", 0) or 0)
        view_count = max(dom_views, net_views)
        # Лайки с сетки; для постов с большим числом просмотров ниже — дообогащение через enrich.
        like_count = dom_likes
        posts.append({
            "external_id":   post_id,
            "description":   p.get("text", ""),
            "thumbnail_url": p.get("thumb", ""),
            "post_url":      post_url_final,
            "view_count":    view_count,
            "like_count":    like_count,
            "comment_count": max(_parse_count(p.get("comments", 0)), int(nmeta.get("comments", 0) or 0)),
            "share_count":   max(_parse_count(p.get("shares", 0)), int(nmeta.get("shares", 0) or 0)),
            "posted_at":     posted_at,
        })

    min_detail_v = _facebook_detail_likes_min_views()
    if min_detail_v > 0:
        cleared = 0
        for p in posts:
            try:
                v = int(p.get("view_count") or 0)
            except (TypeError, ValueError):
                v = 0
            if v <= min_detail_v:
                if int(p.get("like_count") or 0) != 0:
                    cleared += 1
                p["like_count"] = 0
        if cleared:
            print(
                f"[facebook_worker] лайки с сетки сброшены (view_count ≤ {min_detail_v}): "
                f"{cleared} пост(ов)",
                file=sys.stderr,
            )

    _facebook_zero_like_if_equals_views(posts)
    _facebook_dedupe_phantom_likes(posts)
    reels_sk_url: str | None = (reels_sk_url_saved or "").strip() or None
    if not reels_sk_url:
        ufin = (page.url or "").lower()
        if "sk=reels_tab" in ufin or "sk%3dreels_tab" in ufin:
            reels_sk_url = page.url
    if not reels_sk_url and on_reels_sk:
        reels_sk_url = _facebook_reels_sk_url_from_nav(nav_url) or None
    # Всегда иметь URL вкладки Reels для same-tab (возврат после /reel/…): иначе enrich не заходит в пост.
    if not (reels_sk_url or "").strip():
        reels_sk_url = _facebook_reels_sk_url_from_nav(nav_url) or None
    print(
        f"[facebook_worker] enrich: restore_sk={'1' if (reels_sk_url or '').strip() else '0'} "
        f"posts={len(posts)}",
        file=sys.stderr,
    )
    detail_like_updates = 0
    try:
        detail_like_updates = await _facebook_enrich_reel_likes_from_detail(
            page, posts, reels_sk_url=reels_sk_url
        )
    except Exception as exc:
        print(f"[facebook_worker] enrich reel likes: {exc}", file=sys.stderr)
    _facebook_zero_like_if_equals_views(posts)
    _facebook_dedupe_phantom_likes(posts)
    _facebook_zero_likes_if_like_is_other_post_view_count(posts)

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
            "reel_detail_like_posts_updated": detail_like_updates,
        },
    }


async def run_once(arg: dict) -> None:
    arg = dict(arg)
    username = arg["username"].lstrip("@")
    _wu = _load_worker_utils()
    try:
        async with async_playwright() as pw:
            context, _browser = await _launch_facebook_context(pw, _wu)
            page = await _facebook_refresh_page(context)
            try:
                result = await _run_with_page(username, page, _wu)
            except (KeyboardInterrupt, SystemExit):
                raise
            except BaseException as exc:
                _write_response({"error": f"Ошибка worker: {exc}"})
                await _wu.finish_cli_session_keep_browser_by_default("facebook_worker", context, _browser)
                return
            _write_response(result)
            await _wu.finish_cli_session_keep_browser_by_default("facebook_worker", context, _browser)
    except BaseException as exc:
        print(f"[facebook_worker] exception: {exc}", file=sys.stderr)
        _write_response({"error": f"Ошибка: {exc}"})


def _write_response(payload: dict) -> None:
    from platforms.worker_json_stdout import write_json_line

    write_json_line(payload)


def _payload_refresh_warm_enabled(payload: dict) -> bool:
    """Прогрев только если Django передал refresh_warm_enabled (галочка в расписании)."""
    v = payload.get("refresh_warm_enabled")
    if v is None:
        return False
    if isinstance(v, bool):
        return v
    return str(v).strip().lower() in {"1", "true", "yes", "on"}


def _facebook_state_path(_wu) -> Path:
    return _wu.state_file_path("facebook", _wu.default_profile_dir())


async def _collapse_extra_facebook_pages(context) -> None:
    """Одна вкладка: лишние about:blank после restore / сбойного перезапуска."""
    while len(context.pages) > 1:
        try:
            await context.pages[-1].close()
        except Exception:
            break


async def _launch_facebook_context(pw, _wu):
    """
    Один Chromium на демон: cookies из facebook_state.json, если файл есть.
    force_persistent=True только без state — иначе «второе» окно без авторизации.
    """
    sf = _facebook_state_path(_wu)
    force_persistent = not sf.exists()
    if sf.exists():
        print(
            f"[facebook_worker] сессия из {sf.name} (импорт в Настройках → Facebook)",
            file=sys.stderr,
            flush=True,
        )
    else:
        print(
            "[facebook_worker] WARNING: facebook_state.json нет — persistent-профиль "
            "может быть без входа. Импортируйте cookies в Настройках.",
            file=sys.stderr,
            flush=True,
        )
    context, browser = await _wu.launch_context(
        pw,
        platform="facebook",
        locale="ru-RU",
        force_persistent=force_persistent,
    )
    await _collapse_extra_facebook_pages(context)
    page = await _facebook_refresh_page(context)
    try:
        u = (page.url or "").strip().lower()
        if not u or u.startswith("about:"):
            await page.goto(
                "https://www.facebook.com/",
                wait_until="domcontentloaded",
                timeout=NAV_TIMEOUT,
            )
    except Exception as exc:
        print(
            f"[facebook_worker] не удалось открыть facebook.com при старте: {exc}",
            file=sys.stderr,
            flush=True,
        )
    return context, browser


async def _facebook_refresh_page(context):
    pages = list(context.pages)
    if not pages:
        return await context.new_page()
    for p in pages:
        try:
            u = (p.url or "").strip().lower()
            if u and u not in ("about:blank", "about:home", "about:newtab"):
                return p
        except Exception:
            pass
    return pages[0]


async def daemon_main(*, cli_first_json: str | None = None) -> None:
    _wu = _load_worker_utils()
    async with async_playwright() as pw:
        context, _browser = await _launch_facebook_context(pw, _wu)
        refresh_page = await _facebook_refresh_page(context)
        warm_page = None
        warm_task: asyncio.Task | None = None
        warm_progress_path: Path | None = None

        async def _ensure_refresh_page() -> None:
            nonlocal refresh_page
            try:
                if refresh_page is not None and not refresh_page.is_closed():
                    return
            except Exception:
                pass
            print(
                "[facebook_worker] вкладка съёма закрыта — открываю новую в том же Chromium",
                file=sys.stderr,
            )
            refresh_page = await context.new_page()

        async def _stop_parallel_warm() -> dict:
            nonlocal warm_task, warm_page, warm_progress_path
            if warm_progress_path is not None:
                try:
                    from platforms.warm_progress import write_warm_progress

                    write_warm_progress(
                        warm_progress_path,
                        platform="facebook",
                        cancel_requested=True,
                        status="cancelled",
                    )
                except Exception:
                    pass
            task = warm_task
            warm_task = None
            stats: dict = {}
            if task is not None and not task.done():
                task.cancel()
                try:
                    stats = await task
                except asyncio.CancelledError:
                    stats = {"cancelled": True, "warm_parallel": True}
                except Exception as exc:
                    stats = {"error": str(exc), "warm_parallel": True}
            elif task is not None:
                try:
                    stats = task.result()
                except Exception:
                    stats = {}
            warm_progress_path = None
            return stats

        async def _start_parallel_warm(payload: dict) -> dict:
            nonlocal warm_task, warm_page, warm_progress_path
            await _stop_parallel_warm()
            prog = (payload.get("progress_path") or "").strip()
            warm_progress_path = Path(prog) if prog else None
            if warm_page is None or warm_page.is_closed():
                warm_page = await context.new_page()
                print(
                    "[facebook_worker] прогрев Reels — вторая вкладка; съём профилей — в первой",
                    file=sys.stderr,
                )
            from platforms.facebook.warm_session import (
                WarmFacebookConfig,
                warm_facebook_until_cancelled,
            )

            sp = None
            if hasattr(_wu, "state_file_path"):
                sp = _wu.state_file_path("facebook", _wu.default_profile_dir())
            cfg = WarmFacebookConfig()

            async def _warm_runner() -> dict:
                try:
                    return await warm_facebook_until_cancelled(
                        warm_page,
                        _wu,
                        cfg,
                        state_path=sp,
                        context=context,
                        progress_path=warm_progress_path,
                    )
                except asyncio.CancelledError:
                    return {"cancelled": True, "warm_parallel": True}

            warm_task = asyncio.create_task(_warm_runner())
            return {"warm_parallel": True, "started": True, "detail": "Reels · вкладка 2"}

        if cli_first_json is not None and sys.stdin.isatty():
            print(
                "[facebook_worker] Окно остаётся открытым. Следующие задания — "
                "одна строка JSON; конец ввода — Ctrl+Z Enter (Windows) или Ctrl+D (Unix).",
                file=sys.stderr,
            )
        for line in _iter_incoming_json_lines(cli_first_json):
            try:
                payload = json.loads(line)
            except Exception:
                _write_response({"error": "Невалидный JSON payload"})
                continue

            if payload.get("warm_parallel"):
                action = str(payload.get("action") or "start").strip().lower()
                try:
                    if action == "stop":
                        stats = await _stop_parallel_warm()
                        result = {"warm_parallel": True, "stopped": True, **stats}
                    elif not _payload_refresh_warm_enabled(payload):
                        result = {
                            "warm_parallel": True,
                            "skipped": True,
                            "detail": "прогрев выключен (refresh_warm_enabled)",
                        }
                    else:
                        result = await _start_parallel_warm(payload)
                except Exception as exc:
                    _write_response({"error": f"Ошибка worker: {exc}"})
                    continue
                _write_response(result)
                continue

            await _ensure_refresh_page()
            try:
                try:
                    await refresh_page.bring_to_front()
                except Exception:
                    pass
                if payload.get("warm"):
                    if not _payload_refresh_warm_enabled(payload):
                        _write_response({
                            "warm": True,
                            "skipped": True,
                            "detail": "прогрев выключен (refresh_warm_enabled)",
                        })
                        continue
                    from platforms.facebook.warm_session import (
                        WarmFacebookConfig,
                        warm_facebook_on_page,
                    )

                    sp = None
                    if hasattr(_wu, "state_file_path"):
                        sp = _wu.state_file_path("facebook", _wu.default_profile_dir())
                    cfg = WarmFacebookConfig(
                        min_minutes=float(payload.get("min_minutes") or 3),
                        max_minutes=float(payload.get("max_minutes") or 11),
                    )
                    prog = (payload.get("progress_path") or "").strip()
                    progress_path = Path(prog) if prog else None
                    warm_tab = warm_page if warm_page is not None and not warm_page.is_closed() else refresh_page
                    result = await warm_facebook_on_page(
                        warm_tab,
                        _wu,
                        cfg,
                        state_path=sp,
                        context=context,
                        progress_path=progress_path,
                    )
                else:
                    username = str(payload.get("username", "")).lstrip("@")
                    if not username:
                        _write_response({"error": "Не указан username"})
                        continue
                    result = await _run_with_page(username, refresh_page, _wu)
            except Exception as exc:
                _write_response({"error": f"Ошибка worker: {exc}"})
                continue
            _write_response(result)
            await asyncio.sleep(_ms_jitter(PAUSE_BETWEEN_TASKS_MIN_MS, PAUSE_BETWEEN_TASKS_MAX_MS))
        if _facebook_daemon_should_close_browser_on_exit():
            print("[facebook_worker] stdin закрыт — закрываю Chromium (FACEBOOK_DAEMON_CLOSE_BROWSER_ON_EXIT=1)", file=sys.stderr)
            await _wu.close_context(context, _browser)
        else:
            print(
                "[facebook_worker] stdin закрыт — Chromium не закрываем; "
                "процесс в ожидании. Остановите worker / Django или включите "
                "FACEBOOK_DAEMON_CLOSE_BROWSER_ON_EXIT=1 чтобы закрыть браузер.",
                file=sys.stderr,
            )
            await asyncio.Future()


if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "--daemon":
        asyncio.run(daemon_main())
    elif len(sys.argv) >= 3 and sys.argv[1] == "--once":
        _path_arg = sys.argv[2].strip()
        try:
            _p = Path(_path_arg)
            if _p.is_file():
                _once_payload = json.loads(_p.read_text(encoding="utf-8"))
            else:
                _once_payload = json.loads(_path_arg)
        except Exception as exc:
            _write_response({"error": f"Невалидный JSON в --once: {exc}"})
            sys.exit(1)

        asyncio.run(run_once(_once_payload))
    elif len(sys.argv) >= 2:
        asyncio.run(daemon_main(cli_first_json=sys.argv[1]))
    else:
        _write_response({"error": "Отсутствует payload"})
        sys.exit(1)
