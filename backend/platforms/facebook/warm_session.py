"""
Прогрев сессии Facebook: только лента Reels (facebook.com/reel/).

Просмотр и лайки как у warm_tiktok, общая длительность 5–15 мин.
Тот же Chrome-профиль, что у facebook worker.
"""
from __future__ import annotations

import asyncio
import os
import random
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from platforms.tiktok.warm_session import (
    sample_watch_duration_sec,
    watch_duration_summary,
)

_LOG: Callable[[str], None] = lambda msg: print(msg, file=sys.stderr, flush=True)

# Канонический URL вертикальной ленты Reels (не /reels/ и не главная лента).
FACEBOOK_REELS_URL = (
    (os.environ.get("FACEBOOK_WARM_REELS_URL") or "https://www.facebook.com/reel/").strip()
    or "https://www.facebook.com/reel/"
)

_RATE_LIMIT_JS = """
() => {
    const title = (document.title || '').toLowerCase();
    const markers = [
        'временно заблокирован',
        'temporarily blocked',
        'слишком часто использовали',
        'using this feature too often',
    ];
    const body = ((document.body && document.body.innerText) || '').toLowerCase();
    for (const m of markers) {
        if (title.includes(m) || body.includes(m)) return m;
    }
    return '';
}
"""

_REELS_LIKE_JS = r"""
() => {
    const selectors = [
        '[aria-label*="Like" i][role="button"]',
        '[aria-label*="Нравится" i][role="button"]',
        'div[role="button"][aria-label*="Like" i]',
        'div[role="button"][aria-label*="Нравится" i]',
    ];
    for (const sel of selectors) {
        const nodes = document.querySelectorAll(sel);
        for (const el of nodes) {
            const rect = el.getBoundingClientRect();
            if (rect.width < 8 || rect.height < 8) continue;
            if (rect.bottom < 0 || rect.top > window.innerHeight) continue;
            const label = (el.getAttribute('aria-label') || '').toLowerCase();
            if (label.includes('unlike') || label.includes('убрать') || label.includes('понравилось')) continue;
            try { el.click(); return true; } catch (_) {}
        }
    }
    return false;
}
"""


@dataclass
class WarmFacebookConfig:
    min_minutes: float = 5.0
    max_minutes: float = 15.0
    watch_short_prob: float = 0.7
    watch_short_min_sec: float = 1.0
    watch_short_max_sec: float = 6.0
    watch_long_min_sec: float = 20.0
    watch_long_max_sec: float = 45.0
    like_every_min: int = 10
    like_every_max: int = 30
    keep_browser_open: bool = False


def _tiktok_watch_cfg(cfg: WarmFacebookConfig):
    from platforms.tiktok.warm_session import WarmTikTokConfig

    return WarmTikTokConfig(
        watch_short_prob=cfg.watch_short_prob,
        watch_short_min_sec=cfg.watch_short_min_sec,
        watch_short_max_sec=cfg.watch_short_max_sec,
        watch_long_min_sec=cfg.watch_long_min_sec,
        watch_long_max_sec=cfg.watch_long_max_sec,
    )


async def _raise_if_rate_limited(page, *, stage: str) -> None:
    from platforms.facebook.rate_limit import FACEBOOK_RATE_LIMIT_PREFIX

    try:
        marker = await page.evaluate(_RATE_LIMIT_JS)
    except Exception:
        return
    if marker:
        raise RuntimeError(
            f"{FACEBOOK_RATE_LIMIT_PREFIX} ({stage}): {marker}. "
            "Остановите прогрев на 15–60 мин."
        )


async def _wait_manual_login_if_needed(page, _wu, *, timeout_sec: int = 180) -> None:
    url = (page.url or "").lower()
    if "/login" not in url and "checkpoint" not in url:
        return
    _LOG(
        f"[warm_facebook] Требуется вход — войдите в Facebook в окне (до {timeout_sec} с)…",
    )
    deadline = time.monotonic() + timeout_sec
    while time.monotonic() < deadline:
        await asyncio.sleep(1.0)
        url = (page.url or "").lower()
        if "/login" not in url and "checkpoint" not in url:
            if _wu is not None and hasattr(_wu, "wait_for_anti_bot_clear"):
                await _wu.wait_for_anti_bot_clear(page, platform="facebook")
            return
    raise RuntimeError("Не удалось дождаться входа в Facebook.")


async def _try_like_reel(page) -> bool:
    try:
        return bool(await page.evaluate(_REELS_LIKE_JS))
    except Exception:
        return False


async def _go_next_reel(page) -> None:
    try:
        await page.keyboard.press("ArrowDown")
    except Exception:
        pass
    try:
        await page.evaluate(
            "window.scrollBy(0, Math.max(400, Math.floor(window.innerHeight * 0.9)))",
        )
    except Exception:
        pass


def _emit_warm_progress(
    progress_path: Path | None,
    *,
    platform: str,
    status: str,
    planned_sec: float,
    elapsed_sec: float,
    videos: int,
    likes: int,
    detail: str,
) -> None:
    if progress_path is None:
        return
    try:
        from platforms.warm_progress import write_warm_progress

        pct = 0
        if planned_sec > 0:
            pct = min(99, int(round(100 * elapsed_sec / planned_sec)))
        elif elapsed_sec > 0:
            pct = min(95, int(elapsed_sec / 45.0))
        write_warm_progress(
            progress_path,
            platform=platform,
            status=status,
            planned_sec=planned_sec,
            elapsed_sec=elapsed_sec,
            progress_percent=pct,
            videos=videos,
            likes=likes,
            detail=detail,
        )
    except Exception:
        pass


async def _sleep_cancellable(progress_path: Path | None, seconds: float) -> bool:
    from platforms.warm_progress import warm_cancel_requested

    deadline = time.monotonic() + max(0.0, float(seconds))
    while time.monotonic() < deadline:
        if warm_cancel_requested(progress_path):
            return True
        await asyncio.sleep(min(0.45, deadline - time.monotonic()))
    return warm_cancel_requested(progress_path)


async def warm_facebook_on_page(
    page,
    _wu,
    cfg: WarmFacebookConfig,
    *,
    state_path: Path | None = None,
    context=None,
    progress_path: Path | None = None,
) -> dict:
    """Прогрев Reels на уже открытой вкладке (демон worker / refresh_all)."""
    total_sec = random.uniform(cfg.min_minutes, cfg.max_minutes) * 60.0
    total_sec = max(120.0, total_sec)
    watch_cfg = _tiktok_watch_cfg(cfg)
    stats: dict = {
        "warm": True,
        "duration_sec": 0.0,
        "state_path": str(state_path or ""),
        "videos": 0,
        "likes": 0,
    }

    _LOG(
        f"[warm_facebook] только Reels {FACEBOOK_REELS_URL}, ~{total_sec / 60:.1f} мин, "
        f"просмотр: {watch_duration_summary(watch_cfg)}, "
        f"лайк каждые {cfg.like_every_min}–{cfg.like_every_max} роликов",
    )

    session_started = time.monotonic()
    deadline = session_started + total_sec

    _LOG(f"[warm_facebook] открываю {FACEBOOK_REELS_URL}")
    await page.goto(FACEBOOK_REELS_URL, wait_until="domcontentloaded", timeout=60_000)
    await page.wait_for_timeout(2500)
    await _wait_manual_login_if_needed(page, _wu)
    if hasattr(_wu, "wait_for_anti_bot_clear"):
        await _wu.wait_for_anti_bot_clear(page, platform="facebook")
    await _raise_if_rate_limited(page, stage="reels")

    videos = 0
    likes = 0
    next_like_at = random.randint(cfg.like_every_min, cfg.like_every_max)
    warm_detail = "Reels"
    _emit_warm_progress(
        progress_path,
        platform="facebook",
        status="running",
        planned_sec=total_sec,
        elapsed_sec=0.0,
        videos=0,
        likes=0,
        detail=warm_detail,
    )

    while time.monotonic() < deadline:
        from platforms.warm_progress import warm_cancel_requested

        if warm_cancel_requested(progress_path):
            _LOG("[warm_facebook] остановка по запросу пользователя")
            stats["cancelled"] = True
            break
        if hasattr(_wu, "wait_for_anti_bot_clear"):
            try:
                await _wu.wait_for_anti_bot_clear(page, platform="facebook")
            except ValueError as exc:
                _LOG(f"[warm_facebook] {exc}")
                break
        await _raise_if_rate_limited(page, stage="reels")

        watch_sec = sample_watch_duration_sec(watch_cfg)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        if await _sleep_cancellable(progress_path, min(watch_sec, remaining)):
            _LOG("[warm_facebook] остановка по запросу пользователя")
            stats["cancelled"] = True
            break

        videos += 1
        if videos >= next_like_at:
            if await _try_like_reel(page):
                likes += 1
                _LOG(f"[warm_facebook] лайк #{likes} (после {videos} роликов)")
            next_like_at = videos + random.randint(
                cfg.like_every_min, cfg.like_every_max,
            )

        if time.monotonic() >= deadline:
            break
        await _go_next_reel(page)
        if await _sleep_cancellable(progress_path, random.uniform(0.4, 1.8)):
            _LOG("[warm_facebook] остановка по запросу пользователя")
            stats["cancelled"] = True
            break

        _emit_warm_progress(
            progress_path,
            platform="facebook",
            status="running",
            planned_sec=total_sec,
            elapsed_sec=time.monotonic() - session_started,
            videos=videos,
            likes=likes,
            detail=warm_detail,
        )

    stats["duration_sec"] = time.monotonic() - session_started
    stats["planned_sec"] = total_sec
    stats["videos"] = videos
    stats["likes"] = likes

    if state_path and context is not None:
        try:
            await context.storage_state(path=str(state_path))
            _LOG(f"[warm_facebook] сессия сохранена: {state_path}")
        except Exception as exc:
            _LOG(f"[warm_facebook] не удалось сохранить state: {exc}")

    return stats


async def warm_facebook_until_cancelled(
    page,
    _wu,
    cfg: WarmFacebookConfig,
    *,
    state_path: Path | None = None,
    context=None,
    progress_path: Path | None = None,
) -> dict:
    """
    Прогрев Reels на отдельной вкладке, пока не запросят остановку (progress cancel_requested).
    Для параллельного прогрева во время съёма профилей в другой вкладке.
    """
    watch_cfg = _tiktok_watch_cfg(cfg)
    stats: dict = {
        "warm": True,
        "warm_parallel": True,
        "duration_sec": 0.0,
        "planned_sec": 0.0,
        "state_path": str(state_path or ""),
        "videos": 0,
        "likes": 0,
    }
    warm_detail = "Reels · вкладка 2"

    _LOG(
        f"[warm_facebook] параллельный прогрев на второй вкладке ({FACEBOOK_REELS_URL}), "
        f"до окончания обновления FB; просмотр: {watch_duration_summary(watch_cfg)}",
    )

    session_started = time.monotonic()

    _LOG(f"[warm_facebook] открываю {FACEBOOK_REELS_URL}")
    await page.goto(FACEBOOK_REELS_URL, wait_until="domcontentloaded", timeout=60_000)
    await page.wait_for_timeout(2500)
    await _wait_manual_login_if_needed(page, _wu)
    if hasattr(_wu, "wait_for_anti_bot_clear"):
        await _wu.wait_for_anti_bot_clear(page, platform="facebook")
    await _raise_if_rate_limited(page, stage="reels")

    videos = 0
    likes = 0
    next_like_at = random.randint(cfg.like_every_min, cfg.like_every_max)
    _emit_warm_progress(
        progress_path,
        platform="facebook",
        status="running",
        planned_sec=0.0,
        elapsed_sec=0.0,
        videos=0,
        likes=0,
        detail=warm_detail,
    )

    while True:
        from platforms.warm_progress import warm_cancel_requested

        if warm_cancel_requested(progress_path):
            _LOG("[warm_facebook] параллельный прогрев остановлен (конец обновления FB)")
            stats["cancelled"] = True
            break
        if hasattr(_wu, "wait_for_anti_bot_clear"):
            try:
                await _wu.wait_for_anti_bot_clear(page, platform="facebook")
            except ValueError as exc:
                _LOG(f"[warm_facebook] {exc}")
                break
        await _raise_if_rate_limited(page, stage="reels")

        watch_sec = sample_watch_duration_sec(watch_cfg)
        if await _sleep_cancellable(progress_path, watch_sec):
            _LOG("[warm_facebook] параллельный прогрев остановлен")
            stats["cancelled"] = True
            break

        videos += 1
        if videos >= next_like_at:
            if await _try_like_reel(page):
                likes += 1
                _LOG(f"[warm_facebook] лайк #{likes} (после {videos} роликов)")
            next_like_at = videos + random.randint(
                cfg.like_every_min, cfg.like_every_max,
            )

        await _go_next_reel(page)
        if await _sleep_cancellable(progress_path, random.uniform(0.4, 1.8)):
            stats["cancelled"] = True
            break

        _emit_warm_progress(
            progress_path,
            platform="facebook",
            status="running",
            planned_sec=0.0,
            elapsed_sec=time.monotonic() - session_started,
            videos=videos,
            likes=likes,
            detail=warm_detail,
        )

    stats["duration_sec"] = time.monotonic() - session_started
    stats["videos"] = videos
    stats["likes"] = likes

    if state_path and context is not None:
        try:
            await context.storage_state(path=str(state_path))
            _LOG(f"[warm_facebook] сессия сохранена: {state_path}")
        except Exception as exc:
            _LOG(f"[warm_facebook] не удалось сохранить state: {exc}")

    return stats


async def run_warm_facebook_session(
    cfg: WarmFacebookConfig,
    *,
    state_path: Path | None = None,
) -> dict:
    from playwright.async_api import async_playwright

    from platforms.worker_pool import sync_accounts_browser_env

    sync_accounts_browser_env()

    _wu_path = Path(__file__).parent.parent / "worker_utils.py"
    import importlib.util as _ilu

    _wu_spec = _ilu.spec_from_file_location("worker_utils", _wu_path)
    _wu = _ilu.module_from_spec(_wu_spec)
    _wu_spec.loader.exec_module(_wu)

    try:
        from platforms.worker_pool import prepare_facebook_warm_session

        prepare_facebook_warm_session()
    except Exception:
        pass

    sp = Path(state_path) if state_path is not None else None
    if sp is None:
        sp = _wu.state_file_path("facebook", _wu.default_profile_dir())

    _LOG(f"[warm_facebook] профиль: {sp.parent}")
    if sp.exists():
        _LOG(f"[warm_facebook] cookies: {sp}")
    else:
        _LOG(f"[warm_facebook] WARNING: {sp.name} нет — войдите через Настройки → Facebook")

    async with async_playwright() as pw:
        context, browser = await _wu.launch_context(
            pw,
            platform="facebook",
            headless=False,
            locale="ru-RU",
            force_persistent=True,
        )
        page = context.pages[0] if context.pages else await context.new_page()
        try:
            await page.bring_to_front()
        except Exception:
            pass

        stats = await warm_facebook_on_page(
            page, _wu, cfg, state_path=sp, context=context,
        )
        stats["state_path"] = str(sp)

        if cfg.keep_browser_open:
            _LOG(
                f"[warm_facebook] прогрев завершён: ~{stats['duration_sec'] / 60:.1f} мин, "
                f"роликов ~{stats['videos']}, лайков {stats['likes']}. "
                f"State: {stats['state_path']}",
            )
            _LOG(
                "[warm_facebook] браузер оставлен открытым. "
                "Ctrl+C в cmd — выход из manage.py; окно Chrome можно закрыть вручную.",
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
