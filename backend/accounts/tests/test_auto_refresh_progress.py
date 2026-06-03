import uuid
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from accounts.auto_refresh_progress import (
    apify_job_applies_to_current_auto_refresh,
    progress_from_run_detail,
)
from accounts.models import ApifyRefreshJobTrigger


class ProgressFromRunDetailTests(SimpleTestCase):
    def test_items_drive_progress_not_inflated_db_counter(self):
        rd = {
            "items": [
                {"account_id": 1, "status": "queued"},
                {"account_id": 2, "status": "queued"},
            ],
        }
        done, total, pct = progress_from_run_detail(rd, db_total=17, db_done=90)
        self.assertEqual(total, 2)
        self.assertEqual(done, 0)
        self.assertEqual(pct, 0)

    def test_terminal_statuses_count_as_done(self):
        rd = {
            "items": [
                {"account_id": 1, "status": "done"},
                {"account_id": 2, "status": "skipped"},
                {"account_id": 3, "status": "queued"},
            ],
        }
        done, total, pct = progress_from_run_detail(rd, db_total=3, db_done=1)
        self.assertEqual(done, 2)
        self.assertEqual(total, 3)
        self.assertEqual(pct, 67)

    def test_fallback_to_db_when_no_items(self):
        done, total, pct = progress_from_run_detail(None, db_total=10, db_done=4)
        self.assertEqual((done, total, pct), (4, 10, 40))


class ApifyBatchMatchTests(SimpleTestCase):
    def test_stale_batch_ignored(self):
        batch = uuid.uuid4()
        other = uuid.uuid4()
        job = MagicMock()
        job.trigger = ApifyRefreshJobTrigger.SCHEDULER
        job.parent_batch_id = other
        job.account_id = 1

        state = MagicMock()
        state.is_running = True
        state.run_detail = {"apify_batch_id": str(batch), "items": [{"account_id": 1}]}

        with patch("accounts.auto_refresh_progress.AutoRefreshState.get", return_value=state):
            self.assertFalse(apify_job_applies_to_current_auto_refresh(job))

            job.parent_batch_id = batch
            self.assertTrue(apify_job_applies_to_current_auto_refresh(job))
