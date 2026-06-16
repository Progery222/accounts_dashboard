"""Автообновление: не падать целиком из-за is_running и broken pipe worker."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from accounts.auto_refresh_progress import refresh_run_in_progress
from accounts.refresh_state import keep_auto_refresh_run_alive
from platforms.worker_pool import is_worker_transport_error, _is_recoverable_playwright_error


class AutoRefreshResilienceTests(SimpleTestCase):
    def test_refresh_run_in_progress_manual_source(self):
        class Stub:
            is_running = False
            finished_at = None
            source = "manual"
            started_at = object()
            run_detail = {"items": [{"status": "running"}]}

        self.assertTrue(refresh_run_in_progress(Stub(), source="manual"))

    def test_keep_auto_refresh_run_alive_restores_flag(self):
        state = MagicMock()
        state.cancel_requested = False
        state.finished_at = None
        state.source = "manual"
        state.is_running = False
        state.last_error = "Автообновление было прервано перезапуском процесса."

        def refresh_from_db(*, fields):
            return None

        state.refresh_from_db.side_effect = refresh_from_db

        keep_auto_refresh_run_alive(state)

        self.assertTrue(state.is_running)
        self.assertEqual(state.last_error, "")
        state.save.assert_called_once()

    def test_keep_auto_refresh_skips_when_finished(self):
        state = MagicMock()
        state.cancel_requested = False
        state.finished_at = object()
        state.source = "manual"
        state.is_running = False

        keep_auto_refresh_run_alive(state)

        state.save.assert_not_called()

    def test_worker_transport_error_broken_pipe(self):
        self.assertTrue(is_worker_transport_error(BrokenPipeError()))
        self.assertTrue(_is_recoverable_playwright_error("[Errno 32] Broken pipe"))
