import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone

from playwright.async_api import async_playwright

from platforms import worker_utils as _wu
from platforms.worker_json_stdout import write_json_line


async def _fetch_hot_listing(page, subreddit: str, limit: int) -> dict:
    sub = (subreddit or "").strip().lstrip("r/").strip("/")
    if not sub:
        raise ValueError("Не указан subreddit")

    await page.goto(f"https://www.reddit.com/r/{sub}/", wait_until="domcontentloaded", timeout=45_000)
    await _wu.wait_for_anti_bot_clear(page, platform="reddit")
    await page.wait_for_timeout(1000)

    listing = await page.evaluate(
        """async ({ sub, limit }) => {
            const out = { ok: false, status: 0, body: null, text: "" };
            try {
                const resp = await fetch(
                    `https://www.reddit.com/r/${sub}/hot.json?limit=${limit}&raw_json=1`,
                    {
                        method: "GET",
                        credentials: "include",
                        headers: { "accept": "application/json" },
                    },
                );
                out.status = resp.status;
                const ct = resp.headers.get("content-type") || "";
                if (ct.includes("application/json")) {
                    out.body = await resp.json();
                    out.ok = resp.ok;
                    return out;
                }
                out.text = await resp.text();
                out.ok = resp.ok;
                return out;
            } catch (e) {
                out.text = String(e || "");
                return out;
            }
        }""",
        {"sub": sub, "limit": int(limit)},
    )
    if not isinstance(listing, dict):
        raise ValueError("Reddit worker: некорректный ответ listing")
    return listing


def _to_iso(ts) -> str | None:
    if not isinstance(ts, (int, float)):
        return None
    try:
        return datetime.fromtimestamp(float(ts), tz=timezone.utc).isoformat()
    except Exception:
        return None


def _normalize_posts(payload: dict, subreddit: str) -> list[dict]:
    children = (((payload or {}).get("data") or {}).get("children") or [])
    posts: list[dict] = []
    for ch in children:
        data = ch.get("data") if isinstance(ch, dict) else None
        if not isinstance(data, dict):
            continue
        pid = str(data.get("id") or "").strip()
        if not pid:
            continue
        permalink = str(data.get("permalink") or "")
        if permalink.startswith("/"):
            post_url = f"https://www.reddit.com{permalink}"
        elif permalink:
            post_url = permalink
        else:
            post_url = f"https://www.reddit.com/r/{subreddit}/comments/{pid}/"

        thumb = str(data.get("thumbnail") or "")
        if not thumb.startswith("http"):
            thumb = ""

        score = int(data.get("score") or 0)
        try:
            ratio = float(data.get("upvote_ratio") or 0.0)
        except (TypeError, ValueError):
            ratio = 0.0
        # Estimated "all reactions" proxy from score and upvote ratio:
        # total ~= score / (2*ratio - 1), stable only when ratio is away from 0.5.
        if score > 0 and ratio > 0.55:
            denom = (2.0 * ratio) - 1.0
            est_views = int(round(score / denom)) if denom > 0 else score
        else:
            est_views = score

        posts.append({
            "external_id": pid,
            "description": str(data.get("title") or "")[:500],
            "thumbnail_url": thumb,
            "post_url": post_url,
            "view_count": max(score, est_views),
            "like_count": score,  # score is treated as likes
            "comment_count": 0,  # intentionally ignored for this app
            "share_count": 0,
            "posted_at": _to_iso(data.get("created_utc")),
        })
    return posts


async def run_once(arg: dict) -> None:
    subreddit = (arg.get("subreddit") or "").strip()
    limit = max(1, min(100, int(arg.get("limit") or 25)))
    async with async_playwright() as pw:
        context, browser = await _wu.launch_context(
            pw,
            platform="reddit",
            locale="en-US",
            viewport={"width": 1280, "height": 900},
        )
        page = context.pages[0] if context.pages else await context.new_page()
        try:
            listing = await _fetch_hot_listing(page, subreddit, limit)
            status = int(listing.get("status") or 0)
            body = listing.get("body") if isinstance(listing.get("body"), dict) else {}
            if status >= 400 or not body:
                text = str(listing.get("text") or "")[:300]
                raise ValueError(f"Reddit hot.json недоступен (status={status}). {text}")
            data = {"posts": _normalize_posts(body, subreddit)}
            write_json_line(data)
        except (KeyboardInterrupt, SystemExit):
            raise
        except BaseException as e:
            write_json_line({"error": str(e)})
        await _wu.finish_cli_session_keep_browser_by_default("reddit_worker", context, browser)


async def daemon_main() -> None:
    async with async_playwright() as pw:
        context, browser = await _wu.launch_context(
            pw,
            platform="reddit",
            locale="en-US",
            viewport={"width": 1280, "height": 900},
        )
        page = context.pages[0] if context.pages else await context.new_page()
        try:
            for line in sys.stdin:
                line = (line or "").strip()
                if not line:
                    continue
                try:
                    arg = json.loads(line)
                except Exception:
                    write_json_line({"error": "Невалидный JSON payload"})
                    continue
                try:
                    listing = await _fetch_hot_listing(page, str(arg.get("subreddit") or ""), max(1, min(100, int(arg.get("limit") or 25))))
                    status = int(listing.get("status") or 0)
                    body = listing.get("body") if isinstance(listing.get("body"), dict) else {}
                    if status >= 400 or not body:
                        text = str(listing.get("text") or "")[:300]
                        raise ValueError(f"Reddit hot.json недоступен (status={status}). {text}")
                    write_json_line({"posts": _normalize_posts(body, str(arg.get('subreddit') or ''))})
                except Exception as e:
                    write_json_line({"error": str(e)})
        finally:
            if _wu.worker_autoclose_browser_on_daemon_exit():
                await _wu.close_context(context, browser)
            else:
                await _wu.daemon_idle_keep_browser_open("reddit_worker")


def main() -> None:
    parser = argparse.ArgumentParser(description="Reddit worker")
    parser.add_argument("payload", nargs="?", default="")
    parser.add_argument("--daemon", action="store_true")
    args = parser.parse_args()
    if args.daemon:
        asyncio.run(daemon_main())
        return
    try:
        payload = json.loads(args.payload or "{}")
    except Exception:
        payload = {}
    try:
        asyncio.run(run_once(payload))
    except Exception as e:
        write_json_line({"error": str(e)})


if __name__ == "__main__":
    main()
