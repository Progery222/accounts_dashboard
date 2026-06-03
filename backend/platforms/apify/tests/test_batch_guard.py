"""Тесты batch_guard: poller не трогает sync-batch jobs."""
from __future__ import annotations

import uuid
from unittest.mock import MagicMock

from django.test import SimpleTestCase

from platforms.apify.batch_guard import (
    enter_sync_apify_batch,
    is_sync_batch_active,
    leave_sync_apify_batch,
    poller_should_ignore_job,
)


class ApifyBatchGuardTests(SimpleTestCase):
    def tearDown(self) -> None:
        leave_sync_apify_batch()

    def test_sync_batch_active_while_entered(self) -> None:
        batch = uuid.uuid4()
        self.assertFalse(is_sync_batch_active())
        enter_sync_apify_batch(batch)
        self.assertTrue(is_sync_batch_active())
        leave_sync_apify_batch()
        self.assertFalse(is_sync_batch_active())

    def test_poller_ignores_sync_inline_job(self) -> None:
        job = MagicMock(run_detail_extra={"sync_inline": True}, parent_batch_id=uuid.uuid4())
        self.assertTrue(poller_should_ignore_job(job))

    def test_poller_ignores_job_in_active_batch(self) -> None:
        batch = uuid.uuid4()
        enter_sync_apify_batch(batch)
        job = MagicMock(run_detail_extra={}, parent_batch_id=batch)
        self.assertTrue(poller_should_ignore_job(job))
        other = MagicMock(run_detail_extra={}, parent_batch_id=uuid.uuid4())
        self.assertFalse(poller_should_ignore_job(other))


class StopFacebookParallelWarmTests(SimpleTestCase):
    def test_stop_skips_when_worker_not_running_and_no_progress_file(self) -> None:
        from unittest.mock import patch

        from accounts.refresh_all_warm import stop_facebook_parallel_warm

        with patch("platforms.worker_pool.worker_daemon_alive", return_value=False):
            with patch("platforms.worker_pool.call_worker") as call_worker:
                self.assertEqual(stop_facebook_parallel_warm(label="test"), {})
                call_worker.assert_not_called()
