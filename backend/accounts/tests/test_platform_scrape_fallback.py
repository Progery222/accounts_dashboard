from unittest import mock

from django.test import TestCase, override_settings

from accounts.models import Account, Platform, ScrapeBackendConfig
from accounts.platform_scrape_fallback import (
    GENERIC_ERROR_THRESHOLD,
    PlatformBatchFallback,
    is_generic_platform_fallback_trigger_error,
    retry_platform_via_apify_after_playwright_failure,
)
from accounts.tiktok_scrape_fallback import BatchScrapeContext
from platforms.profile_unavailable import PROFILE_UNAVAILABLE_MARK


class PlatformFallbackTriggerTests(TestCase):
    def test_profile_unavailable_is_trigger(self) -> None:
        exc = ValueError(f"{PROFILE_UNAVAILABLE_MARK}Instagram @x: нет страницы")
        self.assertTrue(is_generic_platform_fallback_trigger_error(exc))

    def test_generic_error_not_trigger(self) -> None:
        self.assertFalse(is_generic_platform_fallback_trigger_error(ValueError("timeout")))


@override_settings(APIFY_ENABLED=True, APIFY_TOKEN="test-token")
class PlatformBatchFallbackTests(TestCase):
    def setUp(self) -> None:
        ScrapeBackendConfig.objects.filter(pk=1).update(
            instagram_backend="playwright",
            instagram_fallback_enabled=True,
        )

    def _ig_accounts(self, n: int) -> list[Account]:
        return [
            Account(id=i + 1, username=f"u{i}", platform=Platform.INSTAGRAM)
            for i in range(n)
        ]

    def test_profile_unavailable_activates_apify(self) -> None:
        accounts = self._ig_accounts(1)
        fb = PlatformBatchFallback.for_platform(Platform.INSTAGRAM, accounts)
        self.assertIsNotNone(fb)
        assert fb is not None
        exc = ValueError(f"{PROFILE_UNAVAILABLE_MARK}Instagram @u0: нет")
        with mock.patch(
            "accounts.platform_scrape_fallback._shutdown_platform_worker"
        ) as shutdown:
            self.assertTrue(fb.on_playwright_failure(accounts[0], exc))
            shutdown.assert_called_once_with(Platform.INSTAGRAM)
        self.assertTrue(fb.apify_active())

    def test_threshold_activates_apify(self) -> None:
        accounts = self._ig_accounts(GENERIC_ERROR_THRESHOLD)
        fb = PlatformBatchFallback.for_platform(Platform.INSTAGRAM, accounts)
        assert fb is not None
        with mock.patch("accounts.platform_scrape_fallback._shutdown_platform_worker"):
            for i in range(GENERIC_ERROR_THRESHOLD - 1):
                self.assertFalse(
                    fb.on_playwright_failure(accounts[i], ValueError(f"err{i}"))
                )
                self.assertFalse(fb.apify_active())
            self.assertTrue(
                fb.on_playwright_failure(
                    accounts[GENERIC_ERROR_THRESHOLD - 1],
                    ValueError("err-last"),
                )
            )
        self.assertTrue(fb.apify_active())

    def test_batch_context_use_apify_after_activation(self) -> None:
        accounts = self._ig_accounts(1)
        with mock.patch("accounts.platform_scrape_fallback._shutdown_platform_worker"):
            ctx = BatchScrapeContext.for_accounts(accounts)
            plat = ctx.platform_fallbacks.get(Platform.INSTAGRAM)
            self.assertIsNotNone(plat)
            exc = ValueError(f"{PROFILE_UNAVAILABLE_MARK}Instagram @u0: нет")
            ctx.on_platform_playwright_error(accounts[0], exc)
            self.assertTrue(ctx.use_apify(accounts[0]))

    def test_retry_apify_after_profile_unavailable(self) -> None:
        accounts = self._ig_accounts(1)
        exc = ValueError(f"{PROFILE_UNAVAILABLE_MARK}Instagram @u0: нет")
        with mock.patch("accounts.platform_scrape_fallback._shutdown_platform_worker"):
            ctx = BatchScrapeContext.for_accounts(accounts)
            ctx.on_platform_playwright_error(accounts[0], exc)
            with mock.patch(
                "accounts.scrape_backend.refresh_account_via_apify_sync",
                return_value=accounts[0],
            ) as refresh:
                out = retry_platform_via_apify_after_playwright_failure(
                    accounts[0],
                    exc,
                    batch_ctx=ctx,
                    trigger="bulk",
                    parent_batch_id=mock.Mock(),
                )
        self.assertIs(out, accounts[0])
        refresh.assert_called_once()

    def test_fallback_disabled(self) -> None:
        ScrapeBackendConfig.objects.filter(pk=1).update(instagram_fallback_enabled=False)
        accounts = self._ig_accounts(1)
        ctx = BatchScrapeContext.for_accounts(accounts)
        plat = ctx.platform_fallbacks.get(Platform.INSTAGRAM)
        self.assertIsNotNone(plat)
        assert plat is not None
        self.assertFalse(plat.enabled)
