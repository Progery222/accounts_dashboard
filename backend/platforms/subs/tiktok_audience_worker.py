"""
One-shot Playwright-воркер TikTok для subs: видимое окно Chrome, без демона AccountsStats.

Запуск: python platforms/subs/tiktok_audience_worker.py '<json payload>'
"""
from __future__ import annotations

import asyncio
import json
import os
import random
import sys
from pathlib import Path

# cwd = backend/ при вызове из worker_pool
_PROFILE_DIR = os.environ.get("BROWSER_PROFILE_DIR", "").strip()
if not _PROFILE_DIR:
    _home = Path.home()
    _PROFILE_DIR = str(
        _home / "AppData" / "Local" / "TikStatsChromeProfile"
        if (_home / "AppData").exists()
        else _home / ".config" / "tikstats-chrome-profile"
    )


def _write_response(payload) -> None:
    print(json.dumps(payload, ensure_ascii=True), flush=True)


# Обновляется перед каждым job в bulk-режиме (разные @владельцы / списки enrich).
_SUBS_ACTIVE_ENRICH_USERNAMES: list[str] = []


def _subs_set_active_enrich_usernames(names: list[str] | None) -> None:
    _SUBS_ACTIVE_ENRICH_USERNAMES.clear()
    _SUBS_ACTIVE_ENRICH_USERNAMES.extend(
        str(u or "").strip().lstrip("@").lower() for u in (names or []) if str(u or "").strip()
    )


def _subs_enrich_between_accounts_sec() -> tuple[float, float]:
    """Пауза между подписчиками (сек). SUBS_TIKTOK_ENRICH_GAP_SEC=мин,макс."""
    raw = (os.environ.get("SUBS_TIKTOK_ENRICH_GAP_SEC") or "4,8").strip()
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    if len(parts) >= 2:
        try:
            lo, hi = float(parts[0]), float(parts[1])
            if hi < lo:
                lo, hi = hi, lo
            return max(0.0, lo), max(lo, hi)
        except ValueError:
            pass
    return 4.0, 8.0


def _subs_between_tracked_accounts_sec() -> tuple[float, float]:
    """Пауза между отслеживаемыми TikTok-аккаунтами в bulk. SUBS_TIKTOK_BULK_ACCOUNT_GAP_SEC."""
    raw = (os.environ.get("SUBS_TIKTOK_BULK_ACCOUNT_GAP_SEC") or "6,12").strip()
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    if len(parts) >= 2:
        try:
            lo, hi = float(parts[0]), float(parts[1])
            if hi < lo:
                lo, hi = hi, lo
            return max(0.0, lo), max(lo, hi)
        except ValueError:
            pass
    return 6.0, 12.0


def _install_subs_tiktok_scrape_hooks(enrich_usernames: list[str] | None) -> None:
    """Хуки только в subprocess subs — audience_scrape / audience_skip не меняем."""
    import platforms.audience_skip as skip_mod
    import platforms.tiktok.audience_scrape as mod

    if getattr(mod, "_subs_scrape_hooks_installed", False):
        return

    import platforms.subs.audience_skip as subs_skip_mod

    subs_skip_mod._ORIG_ROWS = skip_mod.existing_audience_member_rows_for_dashboard_account
    _subs_set_active_enrich_usernames(enrich_usernames)

    def _subs_existing_rows_for_dashboard(account_id: int, *, limit: int = 500) -> list[dict]:
        return subs_skip_mod.subs_existing_audience_member_rows(
            account_id,
            limit=limit,
            enrich_usernames=list(_SUBS_ACTIVE_ENRICH_USERNAMES),
        )

    skip_mod.existing_audience_member_rows_for_dashboard_account = (
        _subs_existing_rows_for_dashboard
    )

    _orig_enrich = mod._tiktok_enrich_follower_profile_playwright

    async def _subs_tiktok_enrich_follower_profile_playwright(page, wu, row: dict) -> None:
        try:
            await page.bring_to_front()
        except Exception:
            pass
        await _orig_enrich(page, wu, row)
        lo, hi = _subs_enrich_between_accounts_sec()
        gap = lo + random.random() * (hi - lo)
        u = str(row.get("username") or "").strip().lstrip("@")
        print(
            f"[subs_tiktok_worker] пауза {gap:.1f}s перед следующим профилем"
            + (f" (после @{u})" if u else ""),
            file=sys.stderr,
        )
        await asyncio.sleep(gap)

    mod._tiktok_enrich_follower_profile_playwright = _subs_tiktok_enrich_follower_profile_playwright

    _orig_scrape = mod.scrape_tiktok_audience_followers

    async def _subs_scrape_tiktok_audience_followers(page, wu, *args, **kwargs):
        if kwargs.get("enrich_only"):
            try:
                await page.bring_to_front()
            except Exception:
                pass
        return await _orig_scrape(page, wu, *args, **kwargs)

    mod.scrape_tiktok_audience_followers = _subs_scrape_tiktok_audience_followers
    mod._subs_scrape_hooks_installed = True


async def _create_subs_tiktok_context(pw, _wu):
    from platforms.tiktok.sadcaptcha import sadcaptcha_enabled

    if sadcaptcha_enabled():
        from platforms.tiktok.worker import _create_tiktok_context

        return await _create_tiktok_context(pw, _wu)

    profile_base = Path(_PROFILE_DIR)
    if _wu is not None:
        state_path = _wu.state_file_path("tiktok", profile_base)
    else:
        state_path = profile_base / "tiktok_state.json"

    headless = False
    _default_channel = "chrome" if sys.platform != "linux" else ""
    channel = (os.environ.get("TIKTOK_BROWSER_CHANNEL") or _default_channel).strip()
    launch_kwargs = {
        "headless": headless,
        "args": [
            "--disable-blink-features=AutomationControlled",
            "--start-maximized",
        ],
    }
    if channel:
        launch_kwargs["channel"] = channel
    print(
        f"[subs_tiktok_worker] launch headless={headless} "
        f"channel={channel or 'bundled-chromium'}",
        file=sys.stderr,
    )
    browser = await pw.chromium.launch(**launch_kwargs)
    if state_path.exists():
        context = await browser.new_context(
            storage_state=str(state_path),
            locale="en-US",
            viewport={"width": 1280, "height": 900},
        )
    else:
        context = await browser.new_context(
            locale="en-US",
            viewport={"width": 1280, "height": 900},
        )
    return context, browser, state_path


def _subs_oneshot_should_exit() -> bool:
    """После JSON в stdout завершить процесс (call_worker_oneshot ждёт exit)."""
    return os.environ.get("SUBS_ONESHOT_EXIT", "").strip().lower() in {
        "1", "true", "yes", "on", "y",
    }


async def _subs_finish_session(context, browser) -> None:
    from platforms.worker_utils import (
        close_context,
        finish_cli_session_keep_browser_by_default,
    )

    if _subs_oneshot_should_exit():
        await close_context(context, browser)
        return
    await finish_cli_session_keep_browser_by_default(
        "subs_tiktok_worker", context, browser,
    )


async def subs_tiktok_audience_run_once(data: dict) -> None:
    from playwright.async_api import async_playwright
    from platforms.tiktok.worker import _load_worker_utils, _run_with_context

    _install_subs_tiktok_scrape_hooks(data.get("enrich_usernames"))
    _subs_set_active_enrich_usernames(data.get("enrich_usernames"))
    _wu = _load_worker_utils()

    async with async_playwright() as pw:
        context, browser, state_path = await _create_subs_tiktok_context(pw, _wu)
        try:
            out = await _run_with_context(data, context, _wu, state_path)
        except (KeyboardInterrupt, SystemExit):
            raise
        except BaseException as exc:
            _write_response({"error": f"Ошибка subs worker: {exc}"})
            await _subs_finish_session(context, browser)
            return
        _write_response(out)
        await _subs_finish_session(context, browser)


async def subs_tiktok_audience_run_bulk(data: dict) -> None:
    """Несколько отслеживаемых @аккаунтов в одном окне Chrome (массовый enrich subs)."""
    from playwright.async_api import async_playwright
    from platforms.tiktok.worker import _load_worker_utils, _run_with_context

    jobs = data.get("jobs")
    if not isinstance(jobs, list) or not jobs:
        _write_response({"error": "Пустой список jobs для subs_tiktok_bulk"})
        return

    _install_subs_tiktok_scrape_hooks(None)
    _wu = _load_worker_utils()
    results: list[dict] = []

    async with async_playwright() as pw:
        context, browser, state_path = await _create_subs_tiktok_context(pw, _wu)
        page = context.pages[0] if context.pages else await context.new_page()
        if _wu is not None and hasattr(_wu, "warm_playwright_page_home"):
            await _wu.warm_playwright_page_home(page, "tiktok")

        try:
            for idx, job in enumerate(jobs):
                if not isinstance(job, dict):
                    results.append({"error": "Невалидный job"})
                    continue
                dash_id = job.get("audience_account_id")
                owner = str(job.get("username") or "").strip().lstrip("@")
                print(
                    f"[subs_tiktok_worker] bulk {idx + 1}/{len(jobs)}: @{owner} (id={dash_id})",
                    file=sys.stderr,
                )
                _subs_set_active_enrich_usernames(job.get("enrich_usernames"))
                try:
                    out = await _run_with_context(job, context, _wu, state_path, page=page)
                except BaseException as exc:
                    out = {"error": f"Ошибка subs worker: {exc}"}
                results.append(
                    {
                        "audience_account_id": dash_id,
                        "username": owner,
                        "payload": out,
                    },
                )
                if idx + 1 < len(jobs):
                    lo, hi = _subs_between_tracked_accounts_sec()
                    gap = lo + random.random() * (hi - lo)
                    print(
                        f"[subs_tiktok_worker] пауза {gap:.1f}s перед следующим @аккаунтом",
                        file=sys.stderr,
                    )
                    await asyncio.sleep(gap)
        except (KeyboardInterrupt, SystemExit):
            raise
        except BaseException as exc:
            _write_response({"error": f"Ошибка subs bulk: {exc}"})
            await _subs_finish_session(context, browser)
            return

        _write_response({"subs_tiktok_bulk": True, "results": results})
        await _subs_finish_session(context, browser)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        _write_response({"error": "Отсутствует payload"})
        sys.exit(1)
    try:
        payload = json.loads(sys.argv[1])
    except Exception:
        _write_response({"error": "Невалидный JSON payload"})
        sys.exit(1)
    if payload.get("subs_tiktok_bulk"):
        asyncio.run(subs_tiktok_audience_run_bulk(payload))
    else:
        asyncio.run(subs_tiktok_audience_run_once(payload))
