import asyncio
import importlib.util
import json
import re
import sys
from pathlib import Path

from playwright.async_api import async_playwright

NAV_TIMEOUT = 40_000


def _parse_count(text: str) -> int:
    if not text:
        return 0
    raw = str(text).replace("\xa0", " ").replace("\u202f", " ").strip()
    m_short = re.match(r"^([\d][\d\s.,]*?)\s*([KMB])$", raw, flags=re.I)
    if m_short:
        num = m_short.group(1).replace(" ", "")
        suffix = m_short.group(2).upper()

        if "," in num and "." in num:
            # Mixed separators usually mean thousands+decimal in US format.
            num_norm = num.replace(",", "")
        elif "," in num:
            # "8,256,570" => thousands, "1,2" => decimal comma
            if num.count(",") > 1 or len(num.split(",")[-1]) == 3:
                num_norm = num.replace(",", "")
            else:
                num_norm = num.replace(",", ".")
        else:
            num_norm = num

        try:
            val = float(num_norm)
        except ValueError:
            val = 0.0

        # Guard against malformed values like "2120208.3M".
        if val > 10_000:
            digits = re.sub(r"[^\d]", "", num)
            return int(digits) if digits else 0

        mul = {"K": 1_000, "M": 1_000_000, "B": 1_000_000_000}[suffix]
        return int(val * mul)

    m = re.search(r"([\d][\d\s.,]*)", raw, flags=re.I)
    if not m:
        digits = re.sub(r"[^\d]", "", raw)
        return int(digits) if digits else 0
    num = m.group(1).replace(" ", "")
    digits = re.sub(r"[^\d]", "", num)
    return int(digits) if digits else 0


def _normalize_username(raw: str) -> str:
    s = (raw or "").strip().lstrip("@")
    s = re.sub(r"^https?://(?:www\.)?rumble\.com/", "", s, flags=re.I)
    s = s.split("?", 1)[0].split("#", 1)[0].strip("/")
    parts = [p for p in s.split("/") if p]
    if parts and parts[0].lower() in {"c", "user"}:
        parts = parts[1:]
    if parts and parts[-1].lower() == "about":
        parts = parts[:-1]
    if not parts:
        raise ValueError("Некорректный Rumble username")
    return parts[0].strip()


async def main() -> None:
    wu_path = Path(__file__).parent.parent / "worker_utils.py"
    if not wu_path.exists():
        print(json.dumps({"error": "Внутренняя ошибка: worker_utils.py не найден."}))
        sys.exit(1)
    spec = importlib.util.spec_from_file_location("worker_utils", wu_path)
    wu = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(wu)

    async def fetch_with_page(page, username: str) -> dict:
        await page.goto(f"https://rumble.com/c/{username}/about", wait_until="domcontentloaded", timeout=NAV_TIMEOUT)
        await page.wait_for_timeout(3500)
        await wu.wait_for_anti_bot_clear(page, platform="rumble", timeout_ms=30_000)

        info = await page.evaluate(
            """() => {
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

                function firstXPathText(paths) {
                    for (const xp of paths) {
                        try {
                            const r = document.evaluate(
                                xp,
                                document,
                                null,
                                XPathResult.STRING_TYPE,
                                null
                            );
                            const t = (r.stringValue || "").replace(/\\s+/g, " ").trim();
                            if (t) return t;
                        } catch (_) {}
                    }
                    return "";
                }

                // 1) Precise paths from current Rumble about layout.
                out.followers = firstXPathText([
                    "/html/body/main/div[1]/div[2]/div/div/div[2]/span/span",
                    "/html/body/main/div[1]//span[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'),'followers')]",
                ]);
                out.views = firstXPathText([
                    "/html/body/main/div[2]/div[2]/div/p[2]/text()",
                    "/html/body/main/div[2]//p[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'),'views')]",
                ]);
                out.videos = firstXPathText([
                    "/html/body/main/div[2]/div[2]/div/p[3]/text()",
                    "/html/body/main/div[2]//p[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'),'videos')]",
                ]);

                // 2) Fallback: short exact lines in visible text nodes.
                if (!out.followers || !out.views || !out.videos) {
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
                }
                return out;
            }"""
        )

        follower_count = _parse_count(info.get("followers", ""))
        view_count = _parse_count(info.get("views", ""))
        post_count = _parse_count(info.get("videos", ""))
        title_text = (info.get("title") or "").lower()
        page_href = (info.get("href") or "").lower()
        display_name = info.get("displayName") or username
        if "just a moment" in title_text or "challenge" in page_href:
            raise ValueError("Rumble временно недоступен (антибот-челлендж), попробуйте обновить еще раз")
        return {
            "display_name": display_name,
            "avatar_url": info.get("avatar") or "",
            "bio": info.get("bio") or "",
            "follower_count": follower_count,
            "like_count": 0,
            "view_count": view_count,
            "post_count": post_count,
            "_posts": [],
        }

    rumble_profile_dir = wu.default_profile_dir() / "rumble_chrome_profile"

    async def daemon_loop() -> None:
        async with async_playwright() as pw:
            context, browser = await wu.launch_context(
                pw,
                platform="rumble",
                profile_dir=rumble_profile_dir,
                headless=False,
                locale="en-US",
                force_persistent=True,
                browser_channel="chrome",
            )
            try:
                page = context.pages[0] if context.pages else await context.new_page()
                for line in sys.stdin:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        payload = json.loads(line)
                        username = _normalize_username(payload.get("username", ""))
                        data = await fetch_with_page(page, username)
                        print(json.dumps(data, ensure_ascii=False), flush=True)
                    except Exception as e:
                        print(json.dumps({"error": f"Rumble: {e}"}, ensure_ascii=False), flush=True)
            finally:
                await wu.close_context(context, browser)

    if len(sys.argv) > 1 and sys.argv[1] == "--daemon":
        await daemon_loop()
        return

    arg = json.loads(sys.argv[1])
    username = _normalize_username(arg.get("username", ""))
    try:
        async with async_playwright() as pw:
            context, browser = await wu.launch_context(
                pw,
                platform="rumble",
                profile_dir=rumble_profile_dir,
                headless=False,
                locale="en-US",
                force_persistent=True,
                browser_channel="chrome",
            )
            page = await context.new_page()
            try:
                data = await fetch_with_page(page, username)
            finally:
                await page.close()
                await wu.close_context(context, browser)
        print(json.dumps(data, ensure_ascii=False))
    except Exception as e:
        print(json.dumps({"error": f"Rumble @{username}: {e}"}, ensure_ascii=False))
        sys.exit(1)


asyncio.run(main())
