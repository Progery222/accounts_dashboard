"""SadCaptcha (tiktok-captcha-solver) для Playwright TikTok."""
from __future__ import annotations

import asyncio
import os
import sys

_CAPTCHA_UI_SELECTORS = (
    ".captcha-verify-container, .captcha-disable-scroll, "
    "#captcha-verify-image, #captcha_container"
)


def sync_sadcaptcha_env() -> dict[str, str]:
    """Проставить ключ SadCaptcha в os.environ (manage.py warm / worker)."""
    applied: dict[str, str] = {}
    key = (os.environ.get("SADCAPTCHA_API_KEY") or "").strip()
    enabled_raw = (os.environ.get("SADCAPTCHA_ENABLED") or "").strip().lower()
    if not key or not enabled_raw:
        try:
            from platforms.tiktok.browser_profile import load_profile

            prof = load_profile()
            if not key:
                key = str(prof.get("sadcaptcha_api_key") or "").strip()
            if not enabled_raw:
                enabled_raw = "true" if prof.get("sadcaptcha_enabled") else "false"
        except Exception:
            pass
    if not key:
        try:
            from django.conf import settings as dj_settings

            key = (getattr(dj_settings, "SADCAPTCHA_API_KEY", None) or "").strip()
        except Exception:
            key = ""
    if key:
        os.environ["SADCAPTCHA_API_KEY"] = key
        applied["SADCAPTCHA_API_KEY"] = "(set)"
    if enabled_raw:
        os.environ["SADCAPTCHA_ENABLED"] = enabled_raw
        applied["SADCAPTCHA_ENABLED"] = enabled_raw
    elif "SADCAPTCHA_ENABLED" not in os.environ:
        os.environ["SADCAPTCHA_ENABLED"] = "true" if key else "false"
    return applied


def resolve_sadcaptcha_api_key() -> str:
    sync_sadcaptcha_env()
    for name in ("SADCAPTCHA_API_KEY", "TIKTOK_SADCAPTCHA_API_KEY"):
        v = (os.environ.get(name) or "").strip()
        if v:
            return v
    return ""


def sadcaptcha_enabled() -> bool:
    key = resolve_sadcaptcha_api_key()
    if not key:
        return False
    raw = (os.environ.get("SADCAPTCHA_ENABLED") or "").strip().lower()
    if raw in ("0", "false", "no", "off", "n"):
        return False
    return True


def _sadcaptcha_retries() -> int:
    try:
        return max(1, min(5, int(os.environ.get("SADCAPTCHA_SOLVE_RETRIES", "3"))))
    except (TypeError, ValueError):
        return 3


def _sadcaptcha_detect_timeout_sec() -> int:
    try:
        return max(5, min(30, int(os.environ.get("SADCAPTCHA_DETECT_TIMEOUT_SEC", "12"))))
    except (TypeError, ValueError):
        return 12


async def page_shows_tiktok_captcha(page) -> bool:
    try:
        from platforms.worker_utils import _CHALLENGE_JS

        return bool(await page.evaluate(_CHALLENGE_JS))
    except Exception:
        return False


async def _wait_tiktok_captcha_ui(page, *, timeout_ms: int = 12_000) -> None:
    try:
        await page.wait_for_selector(
            _CAPTCHA_UI_SELECTORS,
            timeout=timeout_ms,
            state="visible",
        )
    except Exception:
        pass
    await asyncio.sleep(0.8)


async def _solve_tiktok_captcha_fallback(solver) -> None:
    """Если identify_captcha не сработал — пробуем типовые solvers по очереди."""
    for name, method in (
        ("puzzle_v2", solver.solve_puzzle_v2),
        ("puzzle_v1", solver.solve_puzzle),
        ("rotate_v2", solver.solve_rotate_v2),
        ("rotate_v1", solver.solve_rotate),
    ):
        try:
            print(f"[tiktok] SadCaptcha: fallback {name}…", file=sys.stderr, flush=True)
            await method(retries=2)
            if await solver.captcha_is_not_present(timeout=4):
                return
        except Exception as exc:
            print(
                f"[tiktok] SadCaptcha: fallback {name} — {type(exc).__name__}: {exc}",
                file=sys.stderr,
                flush=True,
            )


async def solve_tiktok_captcha_if_present(page, *, force: bool = False) -> bool:
    """
    Решить капчу TikTok через REST API SadCaptcha + drag в Playwright.
    force=True — страница уже с капчей (_CHALLENGE_JS), не выходим, если библиотека
    сначала не увидела модалку.
    """
    if not sadcaptcha_enabled():
        return False
    api_key = resolve_sadcaptcha_api_key()
    try:
        from tiktok_captcha_solver import AsyncPlaywrightSolver
    except ImportError as exc:
        print(
            f"[tiktok] SadCaptcha: пакет tiktok-captcha-solver не установлен ({exc})",
            file=sys.stderr,
            flush=True,
        )
        return False

    print(
        "[tiktok] SadCaptcha: решение капчи через API"
        + (" (принудительно)" if force else "")
        + "…",
        file=sys.stderr,
        flush=True,
    )
    solver = AsyncPlaywrightSolver(page, api_key)
    try:
        if force:
            await _wait_tiktok_captcha_ui(page)

        if await solver.captcha_is_present(
            8 if force else _sadcaptcha_detect_timeout_sec(),
        ):
            await solver.solve_captcha_if_present(
                captcha_detect_timeout=8 if force else _sadcaptcha_detect_timeout_sec(),
                retries=_sadcaptcha_retries(),
            )
        elif force and await page_shows_tiktok_captcha(page):
            print(
                "[tiktok] SadCaptcha: модалка на странице, библиотека не распознала — fallback",
                file=sys.stderr,
                flush=True,
            )
            try:
                await solver.solve_captcha_if_present(
                    captcha_detect_timeout=8,
                    retries=1,
                )
            except Exception:
                pass
            if await page_shows_tiktok_captcha(page):
                await _solve_tiktok_captcha_fallback(solver)
        else:
            return False

        cleared = not await page_shows_tiktok_captcha(page)
        if cleared:
            print("[tiktok] SadCaptcha: капча снята", file=sys.stderr, flush=True)
        else:
            print(
                "[tiktok] SadCaptcha: капча всё ещё на экране",
                file=sys.stderr,
                flush=True,
            )
        return cleared
    except Exception as exc:
        print(
            f"[tiktok] SadCaptcha: ошибка ({type(exc).__name__}: {exc})",
            file=sys.stderr,
            flush=True,
        )
        if force and await page_shows_tiktok_captcha(page):
            try:
                await _solve_tiktok_captcha_fallback(solver)
                return not await page_shows_tiktok_captcha(page)
            except Exception:
                pass
        return False


async def solve_tiktok_captcha_for_warm(page) -> None:
    """Прогрев: синхронизировать env и решить капчу, если видна."""
    sync_sadcaptcha_env()
    if not sadcaptcha_enabled():
        print(
            "[warm_tiktok] SadCaptcha выключен (нет SADCAPTCHA_API_KEY в env)",
            file=sys.stderr,
            flush=True,
        )
        return
    if not await page_shows_tiktok_captcha(page):
        return
    await solve_tiktok_captcha_if_present(page, force=True)


async def launch_tiktok_persistent_context(pw, user_data_dir: str, **launch_kwargs):
    """
    launch_persistent_context с расширением SadCaptcha, если задан API-ключ.
    Иначе обычный Chromium persistent context.
    """
    if sadcaptcha_enabled():
        from tiktok_captcha_solver import make_async_playwright_solver_context

        api_key = resolve_sadcaptcha_api_key()
        print(
            "[tiktok] SadCaptcha: Chrome + расширение (основной режим — API)",
            file=sys.stderr,
            flush=True,
        )
        return await make_async_playwright_solver_context(
            pw,
            api_key,
            user_data_dir=user_data_dir,
            **launch_kwargs,
        )
    return await pw.chromium.launch_persistent_context(user_data_dir, **launch_kwargs)
