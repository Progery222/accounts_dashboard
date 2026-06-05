from unittest.mock import patch

from django.test import SimpleTestCase, TestCase

from accounts.facebook_scrape_fallback import (
    FacebookBatchFallback,
    is_facebook_antibot_error,
    is_facebook_fallback_trigger_error,
    retry_facebook_via_apify_after_playwright_failure,
)
from accounts.models import Account, Platform, ScrapeBackendChoice, ScrapeBackendConfig
from accounts.tiktok_scrape_fallback import BatchScrapeContext
from platforms.facebook.rate_limit import FACEBOOK_RATE_LIMIT_PREFIX


class FacebookFallbackTriggerTests(SimpleTestCase):
    def test_rate_limit_is_trigger(self) -> None:
        exc = ValueError(f"{FACEBOOK_RATE_LIMIT_PREFIX} (профиль)")
        self.assertTrue(is_facebook_fallback_trigger_error(exc))

    def test_antibot_is_trigger(self) -> None:
        exc = ValueError(
            "Facebook временно недоступен (антибот-челлендж), "
            "пройдите проверку в открывшемся окне и повторите обновление"
        )
        self.assertTrue(is_facebook_antibot_error(exc))
        self.assertTrue(is_facebook_fallback_trigger_error(exc))

    def test_profile_unavailable_is_trigger(self) -> None:
        self.assertTrue(
            is_facebook_fallback_trigger_error(ValueError("PROFILE_UNAVAILABLE|Страница не найдена"))
        )

    def test_stats_rejection_not_trigger(self) -> None:
        exc = ValueError(
            "Данные выглядят как ошибка или недоступность: нулевые метрики "
            "при ненулевых в базе. Обновление не применено."
        )
        self.assertFalse(is_facebook_fallback_trigger_error(exc))


class FacebookBatchFallbackTests(TestCase):
    def setUp(self) -> None:
        ScrapeBackendConfig.objects.update_or_create(
            pk=1,
            defaults={
                "facebook_backend": ScrapeBackendChoice.PLAYWRIGHT,
                "facebook_fallback_enabled": True,
            },
        )

    def test_effective_apify_after_activate(self) -> None:
        fb = FacebookBatchFallback(
            enabled=True,
            primary_backend=ScrapeBackendChoice.PLAYWRIGHT,
        )
        acc = Account(platform=Platform.FACEBOOK, username="61563706508285")
        self.assertIsNone(fb.effective_use_apify(acc))
        with self.settings(APIFY_ENABLED=True, APIFY_TOKEN="tok"):
            fb.on_playwright_failure(
                acc,
                ValueError(f"{FACEBOOK_RATE_LIMIT_PREFIX} (reels)"),
            )
        self.assertTrue(fb.effective_use_apify(acc))

    def test_rate_limit_activates_apify_in_batch_context(self) -> None:
        with self.settings(APIFY_ENABLED=True, APIFY_TOKEN="tok"):
            accounts = [Account(pk=1, platform=Platform.FACEBOOK, username="61563706508285")]
            ctx = BatchScrapeContext.for_accounts(accounts)
            self.assertIsNotNone(ctx.facebook_fallback)
            exc = ValueError(f"{FACEBOOK_RATE_LIMIT_PREFIX} (профиль)")
            ctx.on_facebook_playwright_error(accounts[0], exc)
            self.assertTrue(ctx.facebook_fallback.apify_active())
            self.assertTrue(ctx.use_apify(accounts[0]))

    def test_retry_apify_after_rate_limit(self) -> None:
        with self.settings(APIFY_ENABLED=True, APIFY_TOKEN="tok"):
            accounts = [Account(pk=2, platform=Platform.FACEBOOK, username="61563706508285")]
            ctx = BatchScrapeContext.for_accounts(accounts)
            exc = ValueError(f"{FACEBOOK_RATE_LIMIT_PREFIX} (reels)")
            ctx.on_facebook_playwright_error(accounts[0], exc)
            with patch(
                "accounts.scrape_backend.refresh_account_via_apify_sync",
                return_value=accounts[0],
            ) as mock_sync:
                out = retry_facebook_via_apify_after_playwright_failure(
                    accounts[0],
                    exc,
                    batch_ctx=ctx,
                    trigger="scheduler",
                    parent_batch_id=__import__("uuid").uuid4(),
                )
            self.assertIs(out, accounts[0])
            mock_sync.assert_called_once()

    def test_fallback_disabled_no_override(self) -> None:
        ScrapeBackendConfig.objects.filter(pk=1).update(facebook_fallback_enabled=False)
        accounts = [Account(pk=3, platform=Platform.FACEBOOK, username="x")]
        ctx = BatchScrapeContext.for_accounts(accounts)
        self.assertIsNotNone(ctx.facebook_fallback)
        self.assertFalse(ctx.facebook_fallback.enabled)
