"""Единая точка: уведомление batch и повтор через Apify после ошибки Playwright."""

from __future__ import annotations

import uuid

from accounts.models import Account, Platform


def notify_playwright_batch_errors(
    account: Account,
    exc: BaseException,
    *,
    batch_ctx,
    fb_batch_guard=None,
) -> None:
    from accounts.facebook_scrape_fallback import handle_facebook_playwright_batch_error

    handle_facebook_playwright_batch_error(
        account,
        exc,
        batch_ctx=batch_ctx,
        fb_batch_guard=fb_batch_guard,
    )
    if batch_ctx is None:
        return
    batch_ctx.on_tiktok_playwright_error(account, exc)
    batch_ctx.on_platform_playwright_error(account, exc)


def try_apify_recovery_after_playwright_failure(
    account: Account,
    exc: BaseException,
    *,
    batch_ctx,
    trigger: str,
    parent_batch_id: uuid.UUID | None,
) -> Account | None:
    if batch_ctx is None or parent_batch_id is None:
        return None
    if account.platform == Platform.TIKTOK:
        from accounts.tiktok_scrape_fallback import retry_tiktok_via_apify_after_captcha

        return retry_tiktok_via_apify_after_captcha(
            account,
            exc,
            batch_ctx=batch_ctx,
            trigger=trigger,
            parent_batch_id=parent_batch_id,
        )
    if account.platform == Platform.FACEBOOK:
        from accounts.facebook_scrape_fallback import (
            retry_facebook_via_apify_after_playwright_failure,
        )

        return retry_facebook_via_apify_after_playwright_failure(
            account,
            exc,
            batch_ctx=batch_ctx,
            trigger=trigger,
            parent_batch_id=parent_batch_id,
        )
    from accounts.platform_scrape_fallback import (
        platforms_with_generic_fallback,
        retry_platform_via_apify_after_playwright_failure,
    )

    if account.platform not in platforms_with_generic_fallback():
        return None
    return retry_platform_via_apify_after_playwright_failure(
        account,
        exc,
        batch_ctx=batch_ctx,
        trigger=trigger,
        parent_batch_id=parent_batch_id,
    )


def apify_fallback_detail_suffix(batch_ctx, account: Account) -> str:
    if batch_ctx is None:
        return ""
    if account.platform == Platform.FACEBOOK:
        fb = getattr(batch_ctx, "facebook_fallback", None)
        return fb.fallback_detail_suffix() if fb is not None else ""
    if account.platform == Platform.TIKTOK:
        fb = getattr(batch_ctx, "tiktok_fallback", None)
        return fb.fallback_detail_suffix() if fb is not None else ""
    from accounts.platform_scrape_fallback import platform_fallback_detail_suffix

    return platform_fallback_detail_suffix(batch_ctx, account)
