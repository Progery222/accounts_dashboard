from django.test import TestCase

from accounts.models import Account, Platform, ScrapeBackendChoice, ScrapeBackendConfig
from accounts.tiktok_scrape_fallback import (
    TIKTOK_NEW_ERROR_THRESHOLD,
    BatchScrapeContext,
    TikTokBatchFallback,
)


class TikTokBatchFallbackTests(TestCase):
    def setUp(self) -> None:
        ScrapeBackendConfig.objects.update_or_create(
            pk=1,
            defaults={
                "tiktok_backend": ScrapeBackendChoice.PLAYWRIGHT,
                "tiktok_fallback_enabled": True,
            },
        )

    def test_effective_apify_after_activate(self) -> None:
        fb = TikTokBatchFallback(
            enabled=True,
            primary_backend=ScrapeBackendChoice.PLAYWRIGHT,
            prior_error_account_ids=set(),
        )
        acc = Account(platform=Platform.TIKTOK, username="u1")
        self.assertIsNone(fb.effective_use_apify(acc))
        fb._try_activate("test", shutdown_playwright=False)
        self.assertTrue(fb.effective_use_apify(acc))

    def test_new_errors_threshold_activates_once(self) -> None:
        with self.settings(APIFY_ENABLED=True, APIFY_TOKEN="tok"):
            fb = TikTokBatchFallback(
                enabled=True,
                primary_backend=ScrapeBackendChoice.PLAYWRIGHT,
                prior_error_account_ids={99},
            )
            for i in range(TIKTOK_NEW_ERROR_THRESHOLD):
                acc = Account(pk=10 + i, platform=Platform.TIKTOK, username=f"u{i}")
                fb.on_playwright_failure(acc, ValueError("ошибка съёма"))
            self.assertTrue(fb.apify_active())
            acc2 = Account(pk=50, platform=Platform.TIKTOK, username="u50")
            fb.on_playwright_failure(acc2, ValueError("ещё ошибка"))
            self.assertTrue(fb.apify_active())

    def test_captcha_activates_apify_not_guard_when_fallback_on(self) -> None:
        with self.settings(APIFY_ENABLED=True, APIFY_TOKEN="tok"):
            accounts = [Account(pk=1, platform=Platform.TIKTOK, username="a")]
            ctx = BatchScrapeContext.for_accounts(accounts)
            self.assertIsNotNone(ctx.tiktok_fallback)
            self.assertIsNone(ctx.tiktok_captcha_guard)
            exc = ValueError("TikTok: время ожидания капчи истекло.")
            ctx.on_tiktok_playwright_error(accounts[0], exc)
            self.assertTrue(ctx.tiktok_fallback.apify_active())
            self.assertTrue(ctx.use_apify(accounts[0]))

    def test_guard_when_fallback_disabled(self) -> None:
        ScrapeBackendConfig.objects.filter(pk=1).update(tiktok_fallback_enabled=False)
        accounts = [Account(pk=1, platform=Platform.TIKTOK, username="a")]
        ctx = BatchScrapeContext.for_accounts(accounts)
        self.assertIsNotNone(ctx.tiktok_captcha_guard)
        exc = ValueError("TikTok: время ожидания капчи истекло.")
        ctx.on_tiktok_playwright_error(accounts[0], exc)
        self.assertTrue(ctx.tiktok_captcha_tripped())
