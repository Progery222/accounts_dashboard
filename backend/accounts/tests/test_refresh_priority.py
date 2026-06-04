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

    @patch("platforms.worker_pool.clear_playwright_refresh_force_stop")
    @patch("platforms.worker_pool.shutdown_playwright_pool_aggressive")
    def test_interrupt_on_first_session_enter(self, mock_shutdown, mock_clear_stop):
        interrupt_audience_scrape_for_account_refresh()
        mock_shutdown.assert_called_once()
        mock_clear_stop.assert_called_once()

    @patch("platforms.worker_pool.clear_playwright_refresh_force_stop")
    @patch("platforms.worker_pool.shutdown_playwright_pool_aggressive")
    def test_session_clears_force_stop_after_interrupt(self, mock_shutdown, mock_clear_stop):
        with account_refresh_priority_session():
            pass
        mock_shutdown.assert_called_once()
        mock_clear_stop.assert_called_once()

    def test_priority_message_non_empty(self):
        self.assertIn("аналитики", PRIORITY_BLOCK_MESSAGE.lower())
