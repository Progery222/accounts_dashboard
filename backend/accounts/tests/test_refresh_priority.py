from unittest.mock import patch

from django.test import SimpleTestCase

from accounts.refresh_priority import (
    PRIORITY_BLOCK_MESSAGE,
    account_refresh_priority_active,
    account_refresh_priority_session,
    interrupt_audience_scrape_for_account_refresh,
)


class RefreshPriorityTests(SimpleTestCase):
    def test_session_blocks_audience_while_active(self):
        self.assertFalse(account_refresh_priority_active())
        with account_refresh_priority_session():
            self.assertTrue(account_refresh_priority_active())
        self.assertFalse(account_refresh_priority_active())

    @patch("accounts.refresh_priority.shutdown_playwright_pool_aggressive", create=True)
    def test_interrupt_on_first_session_enter(self, mock_shutdown):
        with patch(
            "platforms.worker_pool.shutdown_playwright_pool_aggressive",
            mock_shutdown,
        ):
            interrupt_audience_scrape_for_account_refresh()
            mock_shutdown.assert_called_once()

    def test_priority_message_non_empty(self):
        self.assertIn("аналитики", PRIORITY_BLOCK_MESSAGE.lower())
