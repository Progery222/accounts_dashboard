"""Instagram / YouTube / Reddit / Rumble: Playwright→Apify в одном batch-прогоне."""

from __future__ import annotations

import threading
import uuid
from pathlib import Path

from accounts.models import Account, Platform, ScrapeBackendChoice, ScrapeBackendConfig
from platforms.apify.config import apify_enabled
from platforms.profile_unavailable import is_profile_unavailable_error

FALLBACK_DETAIL_PREFIX = "Запасной способ (Apify): "
GENERIC_ERROR_THRESHOLD = 3

_PLATFORM_WORKERS: dict[str, Path] = {
    Platform.INSTAGRAM: Path(__file__).resolve().parents[1] / "platforms" / "instagram" / "worker.py",
    Platform.REDDIT: Path(__file__).resolve().parents[1] / "platforms" / "reddit" / "worker.py",
    Platform.RUMBLE: Path(__file__).resolve().parents[1] / "platforms" / "rumble" / "worker.py",
}

_FALLBACK_CONFIG: dict[str, tuple[str, str, str]] = {
    Platform.INSTAGRAM: (
        "instagram_fallback_enabled",
        "instagram_backend",
        "Instagram",
    ),
    Platform.YOUTUBE: (
        "youtube_fallback_enabled",
        "youtube_backend",
        "YouTube",
    ),
    Platform.REDDIT: (
        "reddit_fallback_enabled",
        "reddit_backend",
        "Reddit",
    ),
    Platform.RUMBLE: (
        "rumble_fallback_enabled",
        "rumble_backend",
        "Rumble",
    ),
}


def platforms_with_generic_fallback() -> frozenset[str]:
    return frozenset(_FALLBACK_CONFIG.keys())


def is_generic_platform_fallback_trigger_error(exc: BaseException) -> bool:
    """Недоступный профиль — немедленный fallback; иначе порог ошибок в batch."""
    return is_profile_unavailable_error(str(exc))


def _shutdown_platform_worker(platform: str) -> None:
    worker = _PLATFORM_WORKERS.get(platform)
    if worker is None:
        return
    try:
        from platforms.worker_pool import shutdown_worker

        shutdown_worker(worker)
    except Exception:
        pass


class PlatformBatchFallback:
    """
    Один прогон bulk / refresh_all / автообновление.

    Основной способ — ScrapeBackendConfig.<platform>_backend.
    При fallback и primary Playwright: после недоступного профиля или
    GENERIC_ERROR_THRESHOLD новых ошибок остальные аккаунты платформы идут через Apify.
    """

    def __init__(
        self,
        *,
        platform: str,
        label: str,
        enabled: bool,
        primary_backend: str,
        prior_error_account_ids: set[int],
    ) -> None:
        self.platform = platform
        self.label = label
        self.enabled = bool(enabled)
        self.primary_backend = (primary_backend or ScrapeBackendChoice.PLAYWRIGHT).strip().lower()
        self._prior_error_ids = set(prior_error_account_ids)
        self._lock = threading.Lock()
        self._apify_active = False
        self._switch_consumed = False
        self._new_error_count = 0
        self._activate_reason = ""

    @classmethod
    def for_platform(cls, platform: str, accounts: list[Account]) -> PlatformBatchFallback | None:
        spec = _FALLBACK_CONFIG.get(platform)
        if spec is None:
            return None
        if not any(getattr(a, "platform", None) == platform for a in accounts):
            return None
        cfg = ScrapeBackendConfig.get()
        fallback_field, backend_field, label = spec
        prior: set[int] = set()
        for a in accounts:
            if a.platform != platform:
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
            platform=platform,
            label=label,
            enabled=bool(getattr(cfg, fallback_field)),
            primary_backend=getattr(cfg, backend_field),
            prior_error_account_ids=prior,
        )

    @classmethod
    def for_accounts(cls, accounts: list[Account]) -> dict[str, PlatformBatchFallback]:
        out: dict[str, PlatformBatchFallback] = {}
        for platform in _FALLBACK_CONFIG:
            fb = cls.for_platform(platform, accounts)
            if fb is not None:
                out[platform] = fb
        return out

    def activate_reason(self) -> str:
        with self._lock:
            return self._activate_reason

    def apify_active(self) -> bool:
        with self._lock:
            return self._apify_active

    def effective_use_apify(self, account: Account) -> bool | None:
        if account.platform != self.platform:
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
                f"Переключение {self.label} на Apify в этом прогоне"
            )
        if shutdown_playwright:
            _shutdown_platform_worker(self.platform)
        return True

    def on_playwright_failure(self, account: Account, exc: BaseException) -> bool:
        if account.platform != self.platform:
            return False
        if is_profile_unavailable_error(str(exc)):
            return self._try_activate(str(exc), shutdown_playwright=True)
        if account.pk and account.pk not in self._prior_error_ids:
            with self._lock:
                if self._switch_consumed:
                    return False
                self._new_error_count += 1
                hit = self._new_error_count >= GENERIC_ERROR_THRESHOLD
            if hit:
                return self._try_activate(
                    f"{self.label}: {GENERIC_ERROR_THRESHOLD} новых ошибок в прогоне — Apify",
                    shutdown_playwright=True,
                )
        return False

    def should_retry_via_apify(self, exc: BaseException) -> bool:
        if is_profile_unavailable_error(str(exc)):
            return True
        return self.apify_active()

    def fallback_detail_suffix(self) -> str:
        r = self.activate_reason()
        if not r:
            return FALLBACK_DETAIL_PREFIX + "повтор через Apify"
        return FALLBACK_DETAIL_PREFIX + r


def platform_fallback_for_account(
    batch_ctx,
    account: Account,
) -> PlatformBatchFallback | None:
    if batch_ctx is None:
        return None
    fallbacks = getattr(batch_ctx, "platform_fallbacks", None) or {}
    return fallbacks.get(account.platform)


def retry_platform_via_apify_after_playwright_failure(
    account: Account,
    exc: BaseException,
    *,
    batch_ctx,
    trigger: str,
    parent_batch_id: uuid.UUID | None,
) -> Account | None:
    fb = platform_fallback_for_account(batch_ctx, account)
    if fb is None or not fb.enabled:
        return None
    if not fb.should_retry_via_apify(exc):
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


def platform_fallback_detail_suffix(batch_ctx, account: Account) -> str:
    fb = platform_fallback_for_account(batch_ctx, account)
    if fb is None:
        return ""
    return fb.fallback_detail_suffix()
