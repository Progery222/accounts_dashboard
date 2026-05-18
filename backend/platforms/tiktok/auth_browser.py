"""
Автозаполнение формы входа TikTok в Playwright (настройки в браузере, setup_tiktok_auth).

TikTok часто показывает сначала выбор способа входа; поля email/username появляются
на /login/phone-or-email/email или после клика по пункту «email».
"""
from __future__ import annotations

import re


async def try_fill_tiktok_login_credentials(page, username: str, password: str) -> bool:
    """
    Пытается ввести логин и пароль без отправки формы. Возвращает True, если оба поля заполнены.
    """
    if not (username and password):
        return False

    async def _fill_visible_fields() -> bool:
        user_selectors = (
            'input[name="username"]',
            'input[type="email"]',
            'input[autocomplete="username"]',
            'input[placeholder*="Email or username" i]',
            'input[placeholder*="email or username" i]',
            'input[placeholder*="phone or email" i]',
            'input[placeholder*="Email" i]',
            'input[placeholder*="username" i]',
            'input[placeholder*="Электронн" i]',
            'input[placeholder*="почт" i]',
            'input[placeholder*="логин" i]',
            'input[placeholder*="телефон" i]',
        )
        user_loc = None
        for sel in user_selectors:
            loc = page.locator(sel).first
            try:
                await loc.wait_for(state="visible", timeout=2500)
                if await loc.count() > 0:
                    user_loc = loc
                    break
            except Exception:
                continue
        if user_loc is None:
            return False
        try:
            await user_loc.click(timeout=5000)
            await user_loc.fill("", timeout=3000)
            await user_loc.fill(username, timeout=8000)
        except Exception:
            return False

        pass_loc = page.locator('input[type="password"]').first
        try:
            await pass_loc.wait_for(state="visible", timeout=10000)
            await pass_loc.fill("", timeout=3000)
            await pass_loc.fill(password, timeout=8000)
        except Exception:
            return False
        return True

    # Прямой URL с формой email/username (актуальная разметка TikTok).
    try:
        await page.goto(
            "https://www.tiktok.com/login/phone-or-email/email",
            wait_until="domcontentloaded",
            timeout=45_000,
        )
        await page.wait_for_timeout(900)
        if await _fill_visible_fields():
            return True
    except Exception:
        pass

    try:
        await page.goto(
            "https://www.tiktok.com/login",
            wait_until="domcontentloaded",
            timeout=45_000,
        )
        await page.wait_for_timeout(1200)
    except Exception:
        return False

    # Ссылки на прямую форму email/username.
    for sel in (
        'a[href*="/login/phone-or-email/email"]',
        'a[href*="phone-or-email/email"]',
        'a[href*="login/email"]',
    ):
        try:
            loc = page.locator(sel).first
            await loc.wait_for(state="visible", timeout=2500)
            await loc.click(timeout=5000)
            await page.wait_for_timeout(900)
            if await _fill_visible_fields():
                return True
        except Exception:
            continue

    # Текстовые кнопки выбора способа входа (EN/RU).
    for pattern in (
        r"Use phone or email",
        r"phone or email",
        r"log in with email",
        r"телефон.*почт",
        r"почт.*телефон",
    ):
        try:
            await page.get_by_text(re.compile(pattern, re.I)).first.click(timeout=4000)
            await page.wait_for_timeout(900)
            if await _fill_visible_fields():
                return True
        except Exception:
            continue

    try:
        items = page.locator('[data-e2e="channel-item"]')
        n = await items.count()
        for i in range(min(n, 12)):
            it = items.nth(i)
            try:
                txt = (await it.inner_text(timeout=2000) or "").lower()
            except Exception:
                continue
            if any(k in txt for k in ("email", "почт", "phone", "телефон")):
                try:
                    await it.click(timeout=5000)
                    await page.wait_for_timeout(900)
                    if await _fill_visible_fields():
                        return True
                except Exception:
                    continue
    except Exception:
        pass

    return await _fill_visible_fields()
