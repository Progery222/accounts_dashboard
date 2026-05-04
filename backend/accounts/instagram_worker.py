"""
Standalone subprocess script — run via accounts/scrapers.py.
Uses the shared per-platform state file (instagram_state.json) when available,
falls back to the persistent Chrome profile.
"""
import asyncio
import json
import re
import sys
from pathlib import Path

from playwright.async_api import async_playwright


async def main():
    arg = json.loads(sys.argv[1])
    username = arg["username"].lstrip("@")
    url = f"https://www.instagram.com/{username}/"

    import importlib.util as _ilu
    _wu_path = Path(__file__).parent / "worker_utils.py"
    _wu_spec = _ilu.spec_from_file_location("worker_utils", _wu_path)
    _wu = _ilu.module_from_spec(_wu_spec)
    _wu_spec.loader.exec_module(_wu)

    async with async_playwright() as pw:
        context, _browser = await _wu.launch_context(
            pw, platform="instagram", locale="en-US",
            viewport={"width": 1280, "height": 900},
        )
        page = context.pages[0] if context.pages else await context.new_page()

        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=45_000)
            await page.wait_for_timeout(2500)

            # Detect redirect to login
            if "accounts/login" in page.url or "challenge" in page.url:
                print(json.dumps({
                    "error": "Instagram требует авторизации — войдите в аккаунт в настройках и повторите."
                }))
                sys.exit(1)

            # Meta description: "1,234 Followers, 567 Following, 89 Posts - ..."
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
                # Fallback: try JSON embedded in page scripts
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

            # ── Posts ─────────────────────────────────────────────────────────
            posts = await page.evaluate("""
                (() => {
                    const results = [];
                    try {
                        const scripts = document.querySelectorAll('script[type="application/json"]');
                        for (const s of scripts) {
                            try {
                                const data = JSON.parse(s.textContent);
                                const text = JSON.stringify(data);
                                const edgeMatch = text.match(/"edge_owner_to_timeline_media":\\{.*?"edges":\\[(.*?)\\]\\}/s);
                                if (edgeMatch) {
                                    const nodes = JSON.parse('[' + edgeMatch[1] + ']');
                                    for (const edge of nodes) {
                                        const n = edge.node || edge;
                                        if (!n.shortcode) continue;
                                        const thumb = n.thumbnail_src || n.display_url || '';
                                        const likes = n.edge_liked_by?.count || n.edge_media_preview_like?.count || 0;
                                        const comments = n.edge_media_to_comment?.count || 0;
                                        const views = n.video_view_count || 0;
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
                            const links = document.querySelectorAll('a[href*="/p/"]');
                            const seen = new Set();
                            for (const a of links) {
                                const m = a.href.match(/\\/p\\/([A-Za-z0-9_-]+)\\//);
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
            """)

        finally:
            await _wu.close_context(context, _browser)

    print(json.dumps({
        "display_name": display_name,
        "avatar_url": avatar_url,
        "bio": bio,
        "follower_count": follower_count,
        "following_count": following_count,
        "like_count": 0,
        "post_count": post_count,
        "_posts": posts or [],
    }))


def _parse(text: str) -> int:
    text = text.strip().replace(',', '')
    m = re.match(r'^([\d]+(?:\.[\d]+)?)\s*([KkMmBb]?)', text.upper())
    if not m:
        return 0
    num = float(m.group(1))
    suffix = m.group(2)
    return int(num * {'K': 1_000, 'M': 1_000_000, 'B': 1_000_000_000}.get(suffix, 1))


asyncio.run(main())
