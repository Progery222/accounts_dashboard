"""Playwright warm и автообновление при backend Apify."""
from __future__ import annotations

import threading
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, TestCase

from accounts.models import Account, Platform, ScrapeBackendChoice, ScrapeBackendConfig
from accounts.scrape_backend import (
    accounts_needing_playwright,
    facebook_playwright_warm_needed,
    should_use_apify_for_account,
)
from platforms.apify.config import use_apify_for_platform


class TikTokApifyConfigTests(TestCase):
    def test_use_apify_for_tiktok_when_backend_is_apify(self) -> None:
        ScrapeBackendConfig.objects.update_or_create(
            pk=1,
            defaults={"tiktok_backend": ScrapeBackendChoice.APIFY},
        )
        with self.settings(APIFY_ENABLED=True, APIFY_TOKEN="test-token"):
            self.assertTrue(use_apify_for_platform(Platform.TIKTOK))
            acc = Account(platform=Platform.TIKTOK, username="testuser")
            self.assertTrue(should_use_apify_for_account(acc))
            self.assertEqual(accounts_needing_playwright([acc]), [])

    def test_tiktok_playwright_when_backend_is_playwright(self) -> None:
        ScrapeBackendConfig.objects.update_or_create(
            pk=1,
            defaults={"tiktok_backend": ScrapeBackendChoice.PLAYWRIGHT},
        )
        with self.settings(APIFY_ENABLED=True, APIFY_TOKEN="test-token"):
            self.assertFalse(use_apify_for_platform(Platform.TIKTOK))
            acc = Account(platform=Platform.TIKTOK, username="testuser")
            self.assertFalse(should_use_apify_for_account(acc))
            self.assertEqual(accounts_needing_playwright([acc]), [acc])


class FacebookPlaywrightWarmNeededTests(TestCase):
    def test_no_warm_when_facebook_backend_is_apify(self) -> None:
        ScrapeBackendConfig.objects.update_or_create(
            pk=1,
            defaults={"facebook_backend": ScrapeBackendChoice.APIFY},
        )
        accounts = [
            Account(platform=Platform.FACEBOOK, username="testpage"),
        ]
        self.assertFalse(facebook_playwright_warm_needed(accounts))

    def test_warm_when_facebook_backend_is_playwright(self) -> None:
        ScrapeBackendConfig.objects.update_or_create(
            pk=1,
            defaults={"facebook_backend": ScrapeBackendChoice.PLAYWRIGHT},
        )
        accounts = [
            Account(platform=Platform.FACEBOOK, username="testpage"),
        ]
        self.assertTrue(facebook_playwright_warm_needed(accounts))


class AfterNetworkRefreshApifyTests(SimpleTestCase):
    def test_after_network_refresh_skips_warm_for_apify_facebook(self) -> None:
        from accounts.refresh_all_warm import RefreshAllWarmTracker

        accounts = [MagicMock(platform=Platform.FACEBOOK)]
        with patch(
            "accounts.refresh_all_warm.facebook_playwright_warm_needed",
            return_value=False,
        ):
            with patch(
                "platforms.apify.config.use_apify_for_platform",
                return_value=True,
            ):
                with patch(
                    "accounts.refresh_all_warm.run_refresh_all_warm",
                ) as mock_warm:
                    tracker = RefreshAllWarmTracker(accounts, label="test")
                    tracker.after_network_refresh(Platform.FACEBOOK)
                    mock_warm.assert_not_called()

    def test_should_use_apify_delegates_to_config(self) -> None:
        acc = MagicMock(platform=Platform.FACEBOOK)
        with patch(
            "accounts.scrape_backend.use_apify_for_platform",
            return_value=True,
        ) as mock_use:
            self.assertTrue(should_use_apify_for_account(acc))
            mock_use.assert_called_once_with(Platform.FACEBOOK)

    def test_after_network_refresh_skips_warm_for_apify_tiktok(self) -> None:
        from accounts.refresh_all_warm import RefreshAllWarmTracker

        accounts = [MagicMock(platform=Platform.TIKTOK)]
        with patch(
            "accounts.refresh_all_warm.facebook_playwright_warm_needed",
            return_value=False,
        ):
            with patch(
                "platforms.apify.config.use_apify_for_platform",
                return_value=True,
            ):
                with patch(
                    "accounts.refresh_all_warm.run_refresh_all_warm",
                ) as mock_warm:
                    tracker = RefreshAllWarmTracker(accounts, label="test")
                    tracker.after_network_refresh(Platform.TIKTOK)
                    mock_warm.assert_not_called()

    def test_after_network_refresh_keeps_playwright_interval_warm(self) -> None:
        """При backend Playwright периодический прогрев FB не отключается."""
        from accounts.refresh_all_warm import RefreshAllWarmTracker

        tracker = RefreshAllWarmTracker.__new__(RefreshAllWarmTracker)
        tracker._label = "test"
        tracker._lock = threading.Lock()
        tracker._counts = {Platform.FACEBOOK: 0}
        tracker._next_at = {Platform.FACEBOOK: 1}
        tracker._parallel_fb_warm = False
        tracker._parallel_warm_stop = threading.Event()

        with patch("platforms.apify.config.use_apify_for_platform", return_value=False):
            with patch(
                "accounts.refresh_all_warm.is_refresh_cancel_requested",
                return_value=False,
            ):
                with patch(
                    "accounts.refresh_all_warm.run_refresh_all_warm",
                ) as mock_warm:
                    tracker.after_network_refresh(Platform.FACEBOOK)
                    mock_warm.assert_called_once_with(
                        Platform.FACEBOOK,
                        label="test",
                    )
