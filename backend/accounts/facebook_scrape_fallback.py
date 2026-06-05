"""Facebook: запасной backend (Playwright→Apify) в рамках одного batch-прогона."""

from __future__ import annotations

import threading
import uuid

from accounts.models import Account, Platform, ScrapeBackendChoice, ScrapeBackendConfig
from platforms.apify.config import apify_enabled
from platforms.facebook.rate_limit import (
    is_facebook_rate_limited_error,
    shutdown_facebook_worker,
)
from platforms.profile_unavailable import is_profile_unavailable_error

FALLBACK_DETAIL_PREFIX = "Запасной способ (Apify): "


def is_facebook_antibot_error(exc: BaseException) -> bool:
    msg = str(exc).lower()
    return "антибот-челлендж" in msg or (
        "anti-bot" in msg and "facebook" in msg
    )


def is_facebook_fallback_trigger_error(exc: BaseException) -> bool:
    """Ошибки 1 (rate limit), 2 (антибот), 7 (профиль недоступен) — см. документацию UI."""
    if is_facebook_rate_limited_error(exc):
        return True
    if is_facebook_antibot_error(exc):
        return True
    return is_profile_unavailable_error(str(exc))


class FacebookBatchFallback:
    """
    Один прогон bulk / refresh_all / автообновление.

    Основной способ — ScrapeBackendConfig.facebook_backend.
    При fallback и primary Playwright: после rate limit, антибота или «профиль недоступен»
    остальные Facebook идут через Apify до конца прогона.
    """

    def __init__(
        self,
        *,
        enabled: bool,
        primary_backend: str,
    ) -> None:
        self.enabled = bool(enabled)
        self.primary_backend = (primary_backend or ScrapeBackendChoice.PLAYWRIGHT).strip().lower()
        self._lock = threading.Lock()
        self._apify_active = False
        self._switch_consumed = False
        self._activate_reason = ""

    @classmethod
    def for_accounts(cls, accounts: list[Account]) -> FacebookBatchFallback | None:
        if not any(getattr(a, "platform", None) == Platform.FACEBOOK for a in accounts):
            return None
        cfg = ScrapeBackendConfig.get()
        return cls(
            enabled=bool(cfg.facebook_fallback_enabled),
            primary_backend=cfg.facebook_backend,
        )

    def activate_reason(self) -> str:
        with self._lock:
            return self._activate_reason

    def apify_active(self) -> bool:
        with self._lock:
            return self._apify_active

    def effective_use_apify(self, account: Account) -> bool | None:
        if account.platform != Platform.FACEBOOK:
            return None
        if self.primary_backend == ScrapeBackendChoice.APIFY:
            return True
        if not self.enabled:
            return None
        with self._lock:
            if self._apify_active:
                return True
        return None

    def _try_activate(self, reason: str) -> bool:
        if not self.enabled or self.primary_backend != ScrapeBackendChoice.PLAYWRIGHT:
            return False
        if not apify_enabled():
            return False
        with self._lock:
            if self._switch_consumed:
                return False
            self._switch_consumed = True
            self._apify_active = True
            self._activate_reason = (reason or "").strip() or (
                "Переключение Facebook на Apify в этом прогоне"
            )
        shutdown_facebook_worker()
        return True

    def on_playwright_failure(self, account: Account, exc: BaseException) -> bool:
        if account.platform != Platform.FACEBOOK:
            return False
        if not is_facebook_fallback_trigger_error(exc):
            return False
        return self._try_activate(str(exc))

    def fallback_detail_suffix(self) -> str:
        r = self.activate_reason()
        if not r:
            return FALLBACK_DETAIL_PREFIX + "повтор через Apify"
        return FALLBACK_DETAIL_PREFIX + r


def handle_facebook_playwright_batch_error(
    account: Account,
    exc: BaseException,
    *,
    batch_ctx,
    fb_batch_guard,
) -> None:
    """
    Rate limit: закрыть Playwright worker; при активном fallback — Apify, иначе trip guard.
    """
    if account.platform != Platform.FACEBOOK:
        return
    if is_facebook_rate_limited_error(exc):
        shutdown_facebook_worker()
    activated = False
    if batch_ctx is not None:
        batch_ctx.on_facebook_playwright_error(account, exc)
        fb = getattr(batch_ctx, "facebook_fallback", None)
        if fb is not None and fb.apify_active():
            activated = True
    if (
        is_facebook_rate_limited_error(exc)
        and fb_batch_guard is not None
        and not activated
    ):
        fb_batch_guard.trip(str(exc))


def retry_facebook_via_apify_after_playwright_failure(
    account: Account,
    exc: BaseException,
    *,
    batch_ctx,
    trigger: str,
    parent_batch_id: uuid.UUID | None,
) -> Account | None:
    if account.platform != Platform.FACEBOOK or not is_facebook_fallback_trigger_error(exc):
        return None
    if batch_ctx is None or parent_batch_id is None:
        return None
    from accounts.scrape_backend import (
        refresh_account_via_apify_sync,
        should_use_apify_for_account,
    )

    if not should_use_apify_for_account(account, batch_ctx=batch_ctx):
        return None

    return refresh_account_via_apify_sync(
        account,
        trigger=trigger,
        parent_batch_id=parent_batch_id,
        batch_ctx=batch_ctx,
    )
