"""Smoke-check: какой движок загружен и открывается ли Chromium."""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

os.environ.setdefault("BROWSER_ENGINE", "patchright")


async def main() -> int:
    from platforms.browser_engine import active_engine, async_playwright, browser_engine_name

    print(f"BROWSER_ENGINE env={browser_engine_name()}", flush=True)
    async with async_playwright() as pw:
        engine = active_engine()
        print(f"loaded engine={engine}", flush=True)
        browser = await pw.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto("about:blank")
        title = await page.title()
        await browser.close()
        print(f"ok title={title!r}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
