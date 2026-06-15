import asyncio
import importlib.util
import json
import os
import re
import sys
from pathlib import Path

from playwright.async_api import async_playwright

from platforms.rumble.parse import about_urls, feed_urls, normalize_username, parse_count

NAV_TIMEOUT = 40_000


def _merge_quality_flags(base: dict, extra: dict) -> dict:
    out = dict(base or {})
    for k, v in (extra or {}).items():
        out[k] = v
    return out


_PAGE_INFO_JS = """() => {
    const out = { displayName: "", bio: "", avatar: "", followers: "", views: "", videos: "", title: "", href: "" };
    out.title = document.title || "";
    out.href = location.href || "";
    const title = document.querySelector('meta[property="og:title"]');
    if (title) out.displayName = (title.getAttribute("content") || "").trim();
    if (!out.displayName) {
        const h1 = document.querySelector("h1");
        if (h1) out.displayName = (h1.textContent || "").trim();
    }
    const desc = document.querySelector('meta[property="og:description"]');
    if (desc) out.bio = (desc.getAttribute("content") || "").trim();
    const img = document.querySelector('meta[property="og:image"]');
    if (img) out.avatar = (img.getAttribute("content") || "").trim();

    const nodes = document.querySelectorAll("p, span, div");
    for (const node of nodes) {
        const t = (node.textContent || "").replace(/\\s+/g, " ").trim();
        if (!t || t.length > 80) continue;
        const m = t.match(/^([0-9][0-9,\\.\\s]*[KMB]?)\\s+(followers?|views?|videos?)$/i);
        if (!m) continue;
        const val = m[1];
        const lbl = m[2].toLowerCase();
        if (!out.followers && lbl.startsWith("follower")) out.followers = val;
        if (!out.views && lbl.startsWith("view")) out.views = val;
        if (!out.videos && lbl.startsWith("video")) out.videos = val;
    }
    return out;
}"""

_POSTS_JS = """() => {
    function parseNum(text) {
        const raw = (text || '').replace(/\\s+/g, ' ').trim();
        if (!raw) return 0;
        const m = raw.match(/([0-9][0-9,\\.\\s]*)([KMBkmb]?)/);
        if (!m) return 0;
        let num = (m[1] || '').replace(/\\s/g, '');
        if (num.includes(',') && num.includes('.')) num = num.replace(/,/g, '');
        else if (num.includes(',') && num.split(',').length === 2 && num.split(',')[1].length !== 3) num = num.replace(',', '.');
        else num = num.replace(/,/g, '');
        let v = Number.parseFloat(num);
        if (!Number.isFinite(v)) return 0;
        const s = (m[2] || '').toUpperCase();
        if (s === 'K') v *= 1000;
        else if (s === 'M') v *= 1000000;
        else if (s === 'B') v *= 1000000000;
        return Math.round(v);
    }
    function rumblePostUrl(raw) {
        const u = (raw || '').replace(/&amp;/g, '&');
        const shorts = u.match(/https:\\/\\/rumble\\.com\\/shorts\\/[a-z0-9]+/i);
        if (shorts) return shorts[0];
        const normal = u.match(/https:\\/\\/rumble\\.com\\/v\\/[a-z0-9]+-/i);
        if (normal) return normal[0].split('?')[0];
        return '';
    }
    function extId(url, videoId) {
        if (videoId) return String(videoId).toLowerCase();
        const shorts = (url || '').match(/\\/shorts\\/([a-z0-9]+)/i);
        if (shorts) return shorts[1].toLowerCase();
        const m = (url || '').match(/\\/([a-z0-9]+)-/i);
        if (m) return m[1].toLowerCase();
        const n = (url || '').match(/\\/([a-z0-9]+)(?:$|[/?#])/i);
        return n ? n[1].toLowerCase() : (url || '');
    }

    const out = [];
    const seen = new Set();

    for (const el of document.querySelectorAll('rum-video-thumbnail')) {
        const videoId = el.getAttribute('video-id') || '';
        const title = (el.getAttribute('title') || '').replace(/\\s+/g, ' ').trim().slice(0, 500);
        const thumb = (el.getAttribute('src') || '').trim();
        const rawUrl = el.getAttribute('url') || '';
        const postUrl = rumblePostUrl(rawUrl) || (videoId ? ('https://rumble.com/v/' + videoId) : '');
        const externalId = extId(postUrl, videoId);
        if (!externalId || seen.has(externalId)) continue;
        seen.add(externalId);
        out.push({
            external_id: externalId,
            description: title,
            thumbnail_url: thumb,
            post_url: postUrl,
            view_count: parseNum(el.getAttribute('views') || '0'),
            like_count: 0,
            comment_count: 0,
            share_count: 0,
            posted_at: el.getAttribute('time') || null,
        });
        if (out.length >= 30) return out;
    }

    const links = Array.from(document.querySelectorAll('a[href]'))
        .map(a => a.getAttribute('href') || '')
        .filter(h => /^\\/(?:v|embed|shorts)\\//i.test(h) || /^https?:\\/\\/rumble\\.com\\/(?:v|embed|shorts)\\//i.test(h));
    for (const href of links) {
        let url = href.startsWith('http') ? href : ('https://rumble.com' + href);
        url = url.split('?')[0];
        const externalId = extId(url, '');
        if (!externalId || seen.has(externalId)) continue;
        seen.add(externalId);
        const a = document.querySelector(`a[href="${href.replace(/"/g, '\\"')}"]`);
        const card = a ? (a.closest('article, li, .video-item, .video-listing-entry, .video-stream') || a.parentElement) : null;
        const text = (card ? card.textContent : a?.textContent || '').replace(/\\s+/g, ' ').trim();
        const titleEl = card?.querySelector('h1, h2, h3, .video-item--title, .video-item__title') || a;
        const title = (titleEl?.textContent || '').replace(/\\s+/g, ' ').trim().slice(0, 500);
        const img = card?.querySelector('img[src], img[data-src]');
        const thumb = (img?.getAttribute('src') || img?.getAttribute('data-src') || '').trim();
        let views = 0;
        const viewsMatch = text.match(/([0-9][0-9,\\.\\s]*[KMBkmb]?)\\s+views?/i);
        if (viewsMatch) views = parseNum(viewsMatch[1]);
        out.push({
            external_id: externalId,
            description: title,
            thumbnail_url: thumb,
            post_url: url,
            view_count: views,
            like_count: 0,
            comment_count: 0,
            share_count: 0,
            posted_at: null,
        });
        if (out.length >= 30) break;
    }
    return out;
}"""


def _page_is_blocked(info: dict) -> bool:
    title_text = (info.get("title") or "").lower()
    page_href = (info.get("href") or "").lower()
    display = (info.get("displayName") or "").lower()
    if display == "404 not found" or "404 not found" in title_text:
        return True
    return "just a moment" in title_text or "challenge" in page_href


async def fetch_with_page(page, username: str, wu) -> dict:
    info: dict | None = None
    for url in about_urls(username):
        await page.goto(url, wait_until="domcontentloaded", timeout=NAV_TIMEOUT)
        await page.wait_for_timeout(2500)
        await wu.wait_for_anti_bot_clear(page, platform="rumble")
        candidate = await page.evaluate(_PAGE_INFO_JS)
        if _page_is_blocked(candidate):
            continue
        info = candidate
        break

    if not info:
        raise ValueError("Rumble временно недоступен (антибот-челлендж), попробуйте обновить еще раз")

    follower_count = parse_count(info.get("followers", ""))
    view_count = parse_count(info.get("views", ""))
    post_count = parse_count(info.get("videos", ""))
    display_name = info.get("displayName") or username

    about_data = {
        "display_name": display_name,
        "avatar_url": info.get("avatar") or "",
        "bio": info.get("bio") or "",
        "follower_count": follower_count,
        "like_count": 0,
        "view_count": view_count,
        "post_count": post_count,
    }

    posts: list[dict] = []
    quality_flags = {
        "about_parsed": True,
        "feed_parsed": False,
        "partial_posts": True,
        "anti_bot_detected": False,
    }

    for url in feed_urls(username):
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=NAV_TIMEOUT)
            await page.wait_for_timeout(2000)
            await wu.wait_for_anti_bot_clear(page, platform="rumble")
            probe = await page.evaluate(_PAGE_INFO_JS)
            if _page_is_blocked(probe):
                continue
            posts_raw = await page.evaluate(_POSTS_JS)
            if isinstance(posts_raw, list) and posts_raw:
                posts = posts_raw
                quality_flags = _merge_quality_flags(
                    quality_flags,
                    {"feed_parsed": True, "partial_posts": bool(post_count and len(posts) < post_count)},
                )
                break
        except Exception:
            continue

    if not post_count and posts:
        about_data["post_count"] = len(posts)

    return {
        **about_data,
        "_posts": posts,
        "_source": "worker",
        "_quality_flags": quality_flags,
    }


async def main() -> None:
    wu_path = Path(__file__).parent.parent / "worker_utils.py"
    if not wu_path.exists():
        print(json.dumps({"error": "Внутренняя ошибка: worker_utils.py не найден."}))
        sys.exit(1)
    spec = importlib.util.spec_from_file_location("worker_utils", wu_path)
    wu = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(wu)

    rumble_profile_dir = wu.default_profile_dir()
    _rumble_default_channel = "chrome" if sys.platform != "linux" else ""
    rumble_channel = (
        os.environ.get("RUMBLE_BROWSER_CHANNEL", _rumble_default_channel).strip() or None
    )

    async def daemon_loop() -> None:
        async with async_playwright() as pw:
            context, browser = await wu.launch_context(
                pw,
                platform="rumble",
                profile_dir=rumble_profile_dir,
                locale="en-US",
                browser_channel=rumble_channel,
            )
            try:
                page = context.pages[0] if context.pages else await context.new_page()
                for line in sys.stdin:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        payload = json.loads(line)
                        username = normalize_username(payload.get("username", ""))
                        data = await fetch_with_page(page, username, wu)
                        print(json.dumps(data, ensure_ascii=False), flush=True)
                    except Exception as e:
                        print(json.dumps({"error": f"Rumble: {e}"}, ensure_ascii=False), flush=True)
            finally:
                if wu.worker_autoclose_browser_on_daemon_exit():
                    await wu.close_context(context, browser)
                else:
                    await wu.daemon_idle_keep_browser_open("rumble_worker")

    if len(sys.argv) > 1 and sys.argv[1] == "--daemon":
        await daemon_loop()
        return

    arg = json.loads(sys.argv[1])
    username = normalize_username(arg.get("username", ""))
    try:
        async with async_playwright() as pw:
            context, browser = await wu.launch_context(
                pw,
                platform="rumble",
                profile_dir=rumble_profile_dir,
                locale="en-US",
                browser_channel=rumble_channel,
            )
            page = await context.new_page()
            try:
                data = await fetch_with_page(page, username, wu)
            except (KeyboardInterrupt, SystemExit):
                raise
            except BaseException as e:
                print(json.dumps({"error": f"Rumble: {e}"}, ensure_ascii=False), flush=True)
                await wu.finish_cli_session_keep_browser_by_default("rumble_worker", context, browser)
                return
            print(json.dumps(data, ensure_ascii=False), flush=True)
            await wu.finish_cli_session_keep_browser_by_default("rumble_worker", context, browser)
    except Exception as e:
        print(json.dumps({"error": f"Rumble @{username}: {e}"}, ensure_ascii=False))
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
