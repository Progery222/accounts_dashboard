"""call_worker не поднимает новый браузер после «Остановить»."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from accounts.refresh_cancel import RefreshCancelledError
from platforms.worker_pool import (
    call_worker,
    clear_playwright_refresh_force_stop,
    mark_playwright_refresh_force_stop,
)


class WorkerPoolStopRetryTests(SimpleTestCase):
    def tearDown(self) -> None:
        clear_playwright_refresh_force_stop()

    @patch(
        "platforms.worker_pool.refresh_stop_requested",
        side_effect=[False, True],
    )
    @patch("platforms.worker_pool._WorkerHandle")
    def test_call_worker_no_retry_after_stop(self, _handle_cls, _stop) -> None:
        worker_path = Path(__file__).resolve().parents[2] / "platforms" / "threads" / "worker.py"
        handle = MagicMock()
        handle.proc.poll.return_value = None
        handle._browser_ready.is_set.return_value = True
        handle.call.side_effect = ValueError("target page, context or browser has been closed")
        key = str(worker_path.resolve())
        with patch("platforms.worker_pool._HANDLES", {key: handle}):
            with self.assertRaises(RefreshCancelledError):
                call_worker(worker_path, {"username": "u"})
        self.assertEqual(handle.call.call_count, 1)

    @patch("platforms.worker_pool._WorkerHandle")
    def test_call_worker_aborts_before_spawn_when_force_stop(self, _handle_cls) -> None:
        worker_path = Path(__file__).resolve().parents[2] / "platforms" / "threads" / "worker.py"
        mark_playwright_refresh_force_stop()
        with patch("platforms.worker_pool._HANDLES", {}):
            with self.assertRaises(RefreshCancelledError):
                call_worker(worker_path, {"username": "u"})
        _handle_cls.assert_not_called()
