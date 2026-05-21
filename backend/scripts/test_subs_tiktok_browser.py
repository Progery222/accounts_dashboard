#!/usr/bin/env python
"""
Временный тест: открыть Chrome для TikTok enrich (как subs).

Примеры (из каталога backend/):
  .venv\\Scripts\\python.exe scripts\\test_subs_tiktok_browser.py --direct
  .venv\\Scripts\\python.exe scripts\\test_subs_tiktok_browser.py --worker --username phil.cuts --member flec_officiel --account-id 277
  .venv\\Scripts\\python.exe scripts\\test_subs_tiktok_browser.py --api --dashboard-account-id 277 --member flec_officiel
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
SUBS_WORKER = BACKEND / "platforms" / "subs" / "tiktok_audience_worker.py"


def _payload(username: str, account_id: int, member: str) -> dict:
    return {
        "audience_followers": True,
        "username": username.lstrip("@").lower(),
        "limit": 100,
        "max_posts_per_follower": 0,
        "audience_account_id": int(account_id),
        "audience_mode": "enrich",
        "list_only": False,
        "enrich_only": True,
        "enrich_usernames": [member.lstrip("@").lower()],
    }


def run_direct() -> int:
    """Только Playwright: launch Chrome + tiktok.com (без Django)."""
    import asyncio

    async def main() -> None:
        from playwright.async_api import async_playwright

        profile = Path.home() / "AppData" / "Local" / "TikStatsChromeProfile"
        state = profile / "tiktok_state.json"
        print(f"[test] profile={profile}", flush=True)
        print(f"[test] state exists={state.exists()}", flush=True)
        async with async_playwright() as pw:
            print("[test] launching Chrome headless=False ...", flush=True)
            browser = await pw.chromium.launch(
                headless=False,
                channel="chrome",
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--start-maximized",
                ],
            )
            ctx_kw = {"locale": "en-US", "viewport": {"width": 1280, "height": 900}}
            if state.exists():
                ctx_kw["storage_state"] = str(state)
            context = await browser.new_context(**ctx_kw)
            page = await context.new_page()
            await page.bring_to_front()
            await page.goto("https://www.tiktok.com/", wait_until="domcontentloaded", timeout=60_000)
            print(f"[test] opened url={page.url!r}", flush=True)
            print("[test] Окно должно быть видно ~25 с. Закройте вручную или ждите.", flush=True)
            await asyncio.sleep(25)
            await context.close()
            await browser.close()
        print("[test] direct OK", flush=True)

    asyncio.run(main())
    return 0


def run_worker(username: str, account_id: int, member: str, *, hold_sec: int) -> int:
    """Запуск platforms/subs/tiktok_audience_worker.py как worker_pool."""
    env = os.environ.copy()
    env["PYTHONPATH"] = str(BACKEND)
    env["BROWSER_HEADLESS"] = "false"
    env["TIKTOK_HEADLESS"] = "false"
    env["WORKER_AUTOCLOSE_BROWSER_ON_EXIT"] = "1"
    env["SUBS_ONESHOT_EXIT"] = "1"
    payload = json.dumps(_payload(username, account_id, member), ensure_ascii=False)
    cmd = [sys.executable, str(SUBS_WORKER), payload]
    print(f"[test] cmd={' '.join(cmd[:2])} <payload>", flush=True)
    t0 = time.time()
    proc = subprocess.run(
        cmd,
        cwd=str(BACKEND),
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=max(120, hold_sec + 90),
    )
    dt = time.time() - t0
    print(f"[test] exit={proc.returncode} elapsed={dt:.1f}s", flush=True)
    if proc.stderr:
        print("--- stderr ---", flush=True)
        print(proc.stderr, flush=True)
    if proc.stdout:
        print("--- stdout ---", flush=True)
        print(proc.stdout, flush=True)
    return 0 if proc.returncode == 0 else 1


def run_api(dashboard_account_id: int, member: str, base: str) -> int:
    url = f"{base.rstrip('/')}/api/accounts/{int(dashboard_account_id)}/audience/refresh/"
    body = {
        "audience_mode": "enrich",
        "enrich_usernames": [member.lstrip("@").lower()],
    }
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "X-Subs-Client": "1",
        },
    )
    print(f"[test] POST {url}", flush=True)
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=600) as resp:
            raw = resp.read().decode("utf-8")
            print(f"[test] HTTP {resp.status} elapsed={time.time()-t0:.1f}s", flush=True)
            print(raw[:2000], flush=True)
    except urllib.error.HTTPError as e:
        print(f"[test] HTTP {e.code} elapsed={time.time()-t0:.1f}s", flush=True)
        print(e.read().decode("utf-8", errors="replace")[:2000], flush=True)
        return 1
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="Тест видимого Chrome для subs TikTok enrich")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--direct", action="store_true", help="Только Playwright → tiktok.com")
    g.add_argument("--worker", action="store_true", help="subs tiktok_audience_worker.py")
    g.add_argument("--api", action="store_true", help="POST audience/refresh с X-Subs-Client")
    p.add_argument("--username", default="phil.cuts")
    p.add_argument("--account-id", type=int, default=277)
    p.add_argument("--member", default="flec_officiel")
    p.add_argument("--dashboard-account-id", type=int, default=277)
    p.add_argument("--api-base", default="http://127.0.0.1:8000")
    p.add_argument("--hold-sec", type=int, default=0, help="(не используется при SUBS_ONESHOT_EXIT)")
    args = p.parse_args()

    if args.direct:
        return run_direct()
    if args.worker:
        return run_worker(args.username, args.account_id, args.member, hold_sec=args.hold_sec)
    return run_api(args.dashboard_account_id, args.member, args.api_base)


if __name__ == "__main__":
    raise SystemExit(main())
