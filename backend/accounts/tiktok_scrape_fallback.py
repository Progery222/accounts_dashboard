"""TikTok: запасной backend (Playwright→Apify) в рамках одного batch-прогона."""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING

from accounts.models import Account, Platform, ScrapeBackendChoice, ScrapeBackendConfig
from platforms.apify.config import apify_enabled, use_apify_for_platform
from platforms.tiktok.captcha_batch import (
    TikTokRefreshBatchGuard,
    is_tiktok_captcha_stall_error,
    shutdown_tiktok_worker,
)

if TYPE_CHECKING:
    pass

TIKTOK_NEW_ERROR_THRESHOLD = 3
FALLBACK_DETAIL_PREFIX = "Запасной способ (Apify): "


class TikTokBatchFallback:
    """
    Один прогон bulk / refresh_all / автообновление.

    Основной способ — из ScrapeBackendConfig.tiktok_backend.
    При включённом fallback и основном Playwright: после капчи или 3 «новых»
    ошибок остальные TikTok идут через Apify; обратно на Playwright в этом прогоне не
    переключаемся (нет цикла).
    """

    def __init__(
        self,
        *,
        enabled: bool,
        primary_backend: str,
        prior_error_account_ids: set[int],
    ) -> None:
        self.enabled = bool(enabled)
        self.primary_backend = (primary_backend or ScrapeBackendChoice.PLAYWRIGHT).strip().lower()
        self._prior_error_ids = set(prior_error_account_ids)
        self._lock = threading.Lock()
        self._apify_active = False
        self._switch_consumed = False
        self._new_error_count = 0
        self._activate_reason = ""

    @classmethod
    def for_accounts(cls, accounts: list[Account]) -> TikTokBatchFallback | None:
        if not any(getattr(a, "platform", None) == Platform.TIKTOK for a in accounts):
            return None
        cfg = ScrapeBackendConfig.get()
        prior: set[int] = set()
        for a in accounts:
            if a.platform != Platform.TIKTOK:
                continue
            if getattr(a, "profile_unavailable", False) and a.pk:
                prior.add(int(a.pk))
        try:
            from accounts.models import AutoRefreshState

            st = AutoRefreshState.get()
            for raw_id in st.last_auto_refresh_error_account_ids or []:
                try:
                    prior.add(int(raw_id))
                except (TypeError, ValueError):
                    continue
        except Exception:
            pass
        return cls(
            enabled=bool(cfg.tiktok_fallback_enabled),
            primary_backend=cfg.tiktok_backend,
            prior_error_account_ids=prior,
        )

    def activate_reason(self) -> str:
        with self._lock:
            return self._activate_reason

    def apify_active(self) -> bool:
        with self._lock:
            return self._apify_active

    def effective_use_apify(self, account: Account) -> bool | None:
        """None — использовать глобальную настройку платформы."""
        if account.platform != Platform.TIKTOK:
            return None
        if self.primary_backend == ScrapeBackendChoice.APIFY:
            return True
        if not self.enabled:
            return None
        with self._lock:
            if self._apify_active:
                return True
        return None

    def _try_activate(self, reason: str, *, shutdown_playwright: bool) -> bool:
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
                "Переключение TikTok на Apify в этом прогоне"
            )
        if shutdown_playwright:
            shutdown_tiktok_worker()
        return True

    def on_playwright_failure(self, account: Account, exc: BaseException) -> bool:
        """Вернуть True, если в этом прогоне включили Apify для оставшихся TikTok."""
        if account.platform != Platform.TIKTOK:
            return False
        if is_tiktok_captcha_stall_error(exc):
            return self._try_activate(str(exc), shutdown_playwright=True)
        if account.pk and account.pk not in self._prior_error_ids:
            with self._lock:
                if self._switch_consumed:
                    return False
                self._new_error_count += 1
                hit = self._new_error_count >= TIKTOK_NEW_ERROR_THRESHOLD
            if hit:
                return self._try_activate(
                    f"TikTok: {TIKTOK_NEW_ERROR_THRESHOLD} новых ошибок в прогоне — Apify",
                    shutdown_playwright=True,
                )
        return False

    def fallback_detail_suffix(self) -> str:
        r = self.activate_reason()
        if not r:
            return FALLBACK_DETAIL_PREFIX + "повтор через Apify"
        return FALLBACK_DETAIL_PREFIX + r


class BatchScrapeContext:
    """Контекст batch-прогона: Apify/Playwright + TikTok fallback."""

    def __init__(
        self,
        accounts: list[Account],
        *,
        tiktok_fallback: TikTokBatchFallback | None = None,
        tiktok_captcha_guard: TikTokRefreshBatchGuard | None = None,
    ) -> None:
        self.tiktok_fallback = tiktok_fallback
        self.tiktok_captcha_guard = tiktok_captcha_guard

    @classmethod
    def for_accounts(cls, accounts: list[Account]) -> BatchScrapeContext:
        tt_fb = TikTokBatchFallback.for_accounts(accounts)
        guard = None
        if tt_fb is None or not tt_fb.enabled:
            if any(getattr(a, "platform", None) == Platform.TIKTOK for a in accounts):
                guard = TikTokRefreshBatchGuard()
        return cls(accounts, tiktok_fallback=tt_fb, tiktok_captcha_guard=guard)

    def use_apify(self, account: Account) -> bool:
        if self.tiktok_fallback is not None:
            override = self.tiktok_fallback.effective_use_apify(account)
            if override is not None:
                return override
        return use_apify_for_platform(account.platform)

    def on_tiktok_playwright_error(self, account: Account, exc: BaseException) -> None:
        if self.tiktok_fallback is not None and self.tiktok_fallback.enabled:
            if self.tiktok_fallback.on_playwright_failure(account, exc):
                return
        if self.tiktok_captcha_guard is not None:
            from platforms.tiktok.captcha_batch import on_tiktok_refresh_error

            on_tiktok_refresh_error(account.platform, exc, self.tiktok_captcha_guard)

    def tiktok_captcha_skip_detail(self) -> str:
        if self.tiktok_captcha_guard is not None:
            return self.tiktok_captcha_guard.error_detail()
        return ""

    def tiktok_captcha_tripped(self) -> bool:
        return bool(
            self.tiktok_captcha_guard is not None and self.tiktok_captcha_guard.is_tripped()
        )
