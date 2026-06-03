"""One-off: verify reverted Threads worker for @yllazenart."""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("WORKER_AUTOCLOSE_BROWSER_ON_EXIT", "1")


async def main() -> int:
    from playwright.async_api import async_playwright

    from platforms.threads.worker import execute_payload, _load_worker_utils

    username = (sys.argv[1] if len(sys.argv) > 1 else "yllazenart").lstrip("@")
    _wu = _load_worker_utils()
    async with async_playwright() as pw:
        context, browser = await _wu.launch_context(pw, platform="threads", locale="en-US")
        page = context.pages[0] if context.pages else await context.new_page()
        try:
            result = await execute_payload(page, _wu, {"username": username})
        finally:
            await _wu.close_context(context, browser)

    out_path = Path(__file__).resolve().parents[1] / "_verify_threads_result.json"
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    if result.get("error"):
        print(f"FAIL: {result['error']}", file=sys.stderr)
        return 1

    posts = result.get("_posts") or []
    print(
        f"OK @{username}: followers={result.get('follower_count')} "
        f"post_count={result.get('post_count')} posts={len(posts)}"
    )
    for p in posts[:5]:
        print(
            f"  {p.get('external_id')}: views={p.get('view_count')} "
            f"likes={p.get('like_count')} comments={p.get('comment_count')}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
