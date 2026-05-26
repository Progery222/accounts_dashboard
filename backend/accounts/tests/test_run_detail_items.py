from django.test import TestCase
from django.utils import timezone

from accounts.run_detail_items import merge_run_detail_item


class RunDetailItemsTests(TestCase):
    def test_status_at_on_terminal_transition(self):
        base = {"account_id": 1, "status": "running", "username": "u"}
        with self.settings(USE_TZ=True):
            merged = merge_run_detail_item(base, {"status": "done", "worker": None})
        self.assertEqual(merged["status"], "done")
        self.assertIn("status_at", merged)
        self.assertIsNotNone(merged["status_at"])

    def test_no_status_at_when_unchanged(self):
        base = {"status": "done", "status_at": "2026-05-25T12:00:00+00:00"}
        merged = merge_run_detail_item(base, {"detail": "ok"})
        self.assertEqual(merged["status_at"], "2026-05-25T12:00:00+00:00")

    def test_status_at_updates_on_skipped(self):
        base = {"status": "queued"}
        merged = merge_run_detail_item(base, {"status": "skipped"})
        self.assertIn("status_at", merged)
