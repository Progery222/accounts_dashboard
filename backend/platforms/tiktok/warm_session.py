"""
Прогрев сессии TikTok: лента For You, случайные просмотры и редкие лайки.

Использует тот же Chrome + tiktok_state.json, что и worker съёма.
"""
from __future__ import annotations

import asyncio
import random
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


_LOG: Callable[[str], None] = lambda msg: print(msg, file=sys.stderr, flush=True)


@dataclass
class WarmTikTokConfig:
    min_minutes: float = 5.0
    max_minutes: float = 25.0
    # Распределение длительности просмотра одного ролика (как у «реального» скролла).
    watch_short_prob: float = 0.7
    watch_short_min_sec: float = 1.0
    watch_short_max_sec: float = 6.0
    watch_long_min_sec: float = 20.0
    watch_long_max_sec: float = 45.0
    like_every_min: int = 10
    like_every_max: int = 30
    feed: str = "foryou"  # foryou | following | home
    keep_browser_open: bool = False


def sample_watch_duration_sec(cfg: WarmTikTokConfig) -> float:
    """70% коротких (1–6 с), 30% длинных (20–45 с) по умолчанию."""
    prob = max(0.0, min(1.0, float(cfg.watch_short_prob)))
    if random.random() < prob:
        lo, hi = cfg.watch_short_min_sec, cfg.watch_short_max_sec
    else:
        lo, hi = cfg.watch_long_min_sec, cfg.watch_long_max_sec
    lo = max(0.5, float(lo))
    hi = max(lo, float(hi))
    return random.uniform(lo, hi)


def watch_duration_summary(cfg: WarmTikTokConfig) -> str:
    p = int(round(max(0.0, min(1.0, float(cfg.watch_short_prob))) * 100))
    return (
        f"{p}% × {cfg.watch_short_min_sec:.0f}–{cfg.watch_short_max_sec:.0f} с, "
        f"{100 - p}% × {cfg.watch_long_min_sec:.0f}–{cfg.watch_long_max_sec:.0f} с"
    )


def feed_url_for(feed: str) -> str:
    f = (feed or "foryou").strip().lower()
    if f in {"following", "follow"}:
        return "https://www.tiktok.com/following"
    if f in {"home", "main"}:
        return "https://www.tiktok.com/"
    return "https://www.tiktok.com/foryou"


_LIKE_BUTTON_JS = r"""
() => {
    const selectors = [
        '[data-e2e="browse-like-icon"]',
        '[data-e2e="like-icon"]',
        '[data-e2e="video-like-icon"]',
        'button[aria-label*="Like" i]',
        'button[aria-label*="like" i]',
        'button[aria-label*="Нравится" i]',
        'button[aria-label*="нравится" i]',
    ];
    for (const sel of selectors) {
        const el = document.querySelector(sel);
        if (!el) continue;
        const btn = el.closest('button') || el;
        try {
            btn.click();
            return true;
        } catch (_) {}
    }
    return false;
}
"""


async def _try_like_current_video(page) -> bool:
    try:
        return bool(await page.evaluate(_LIKE_BUTTON_JS))
    except Exception:
        return False


async def _go_next_video(page) -> None:
    """For You на web: стрелка вниз — следующий ролик."""
    try:
        await page.keyboard.press("ArrowDown")
    except Exception:
        pass
    try:
        await page.evaluate(
            "window.scrollBy(0, Math.max(320, Math.floor(window.innerHeight * 0.85)))",
        )
    except Exception:
        pass


async def _wait_manual_login_if_needed(page, _wu, *, timeout_sec: int = 180) -> None:
    url = (page.url or "").lower()
    if "login" not in url and "passport" not in url:
        return
    _LOG(
        "[warm_tiktok] Требуется вход — войдите в TikTok в открытом окне "
        f"(до {timeout_sec} с)…",
    )
    try:
        await page.wait_for_url("**/tiktok.com/**", timeout=timeout_sec * 1000)
    except Exception as exc:
        raise RuntimeError(
            "Не удалось дождаться входа в TikTok. Войдите вручную и повторите."
        ) from exc
    if _wu is not None and hasattr(_wu, "wait_for_anti_bot_clear"):
        await _wu.wait_for_anti_bot_clear(page, platform="tiktok")


async def run_warm_tiktok_session(
    cfg: WarmTikTokConfig,
    *,
    state_path: Path | None = None,
) -> dict:
    """
    Открыть браузер, прогреть ленту, сохранить storage_state.
    Возвращает статистику: duration_sec, videos, likes, state_path.
    """
    from playwright.async_api import async_playwright

    from platforms.worker_pool import sync_accounts_browser_env
    from platforms.tiktok.worker import _create_tiktok_context, _load_worker_utils

    sync_accounts_browser_env()
    _wu = _load_worker_utils()
    if _wu is None:
        raise RuntimeError("worker_utils недоступен")

    try:
        from platforms.worker_pool import shutdown_all_workers

        shutdown_all_workers()
    except Exception:
        pass

    duration_sec = random.uniform(cfg.min_minutes, cfg.max_minutes) * 60.0
    duration_sec = max(60.0, duration_sec)
    url = feed_url_for(cfg.feed)

    stats = {
        "duration_sec": 0.0,
        "videos": 0,
        "likes": 0,
        "state_path": "",
    }

    sp = Path(state_path) if state_path is not None else None
    if sp is None and _wu is not None and hasattr(_wu, "state_file_path"):
        sp = _wu.state_file_path("tiktok", _wu.default_profile_dir())
    if sp is None:
        sp = Path("tiktok_state.json")

    _LOG(f"[warm_tiktok] профиль: {sp.parent}")
    if sp.exists():
        _LOG(f"[warm_tiktok] cookies: {sp}")
    else:
        _LOG(
            f"[warm_tiktok] WARNING: {sp} не найден — войдите через Настройки → TikTok "
            "или manage.py setup_tiktok_auth",
        )

    async with async_playwright() as pw:
        context, browser, sp = await _create_tiktok_context(pw, _wu, state_path=sp)
        stats["state_path"] = str(sp)

        page = context.pages[0] if context.pages else await context.new_page()
        try:
            await page.bring_to_front()
        except Exception:
            pass

        _LOG(f"[warm_tiktok] лента: {url}")
        if hasattr(_wu, "tiktok_goto_with_403_recovery"):
            await _wu.tiktok_goto_with_403_recovery(page, url, timeout_ms=60_000)
        else:
            await page.goto(url, wait_until="domcontentloaded", timeout=60_000)

        await _wait_manual_login_if_needed(page, _wu)
        if hasattr(_wu, "wait_for_anti_bot_clear"):
            await _wu.wait_for_anti_bot_clear(page, platform="tiktok")

        await page.wait_for_timeout(2000)
        _LOG(
            f"[warm_tiktok] прогрев ~{duration_sec / 60:.1f} мин "
            f"(просмотр: {watch_duration_summary(cfg)}, "
            f"лайк каждые {cfg.like_every_min}–{cfg.like_every_max} роликов)",
        )

        started = time.monotonic()
        deadline = started + duration_sec
        videos = 0
        likes = 0
        next_like_at = random.randint(cfg.like_every_min, cfg.like_every_max)

        while time.monotonic() < deadline:
            if hasattr(_wu, "wait_for_anti_bot_clear"):
                try:
                    await _wu.wait_for_anti_bot_clear(page, platform="tiktok")
                except ValueError as exc:
                    _LOG(f"[warm_tiktok] {exc}")
                    break

            watch_sec = sample_watch_duration_sec(cfg)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            await asyncio.sleep(min(watch_sec, remaining))

            videos += 1
            if videos >= next_like_at:
                if await _try_like_current_video(page):
                    likes += 1
                    _LOG(f"[warm_tiktok] лайк #{likes} (после {videos} роликов)")
                next_like_at = videos + random.randint(
                    cfg.like_every_min, cfg.like_every_max,
                )

            if time.monotonic() >= deadline:
                break
            await _go_next_video(page)
            await asyncio.sleep(random.uniform(0.4, 1.8))

        stats["duration_sec"] = time.monotonic() - started
        stats["videos"] = videos
        stats["likes"] = likes

        if sp:
            try:
                await context.storage_state(path=str(sp))
                _LOG(f"[warm_tiktok] сессия сохранена: {sp}")
            except Exception as exc:
                _LOG(f"[warm_tiktok] не удалось сохранить state: {exc}")

        if cfg.keep_browser_open:
            _LOG(
                "[warm_tiktok] браузер оставлен открытым (--keep-open). "
                "Закройте окно или завершите процесс вручную.",
            )
            await asyncio.Future()
        else:
            try:
                await context.close()
            except Exception:
                pass
            if browser is not None:
                try:
                    await browser.close()
                except Exception:
                    pass

    return stats
