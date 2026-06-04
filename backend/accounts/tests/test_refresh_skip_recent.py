from datetime import timedelta
from unittest.mock import MagicMock

from django.test import SimpleTestCase
from django.utils import timezone

from accounts.parallel_account_queue import ParallelAccountQueue
from accounts.refresh_skip_recent import (
    apply_upfront_skip_recent,
    build_initial_run_detail_items,
    initial_run_detail_item,
    should_skip_account_recent,
)


class RefreshSkipRecentTests(SimpleTestCase):
    def test_should_skip_when_updated_after_cutoff(self):
        cutoff = timezone.now() - timedelta(hours=6)
        account = MagicMock(updated_at=timezone.now() - timedelta(hours=1))
        self.assertTrue(should_skip_account_recent(account, cutoff))

    def test_should_not_skip_when_stale(self):
        cutoff = timezone.now() - timedelta(hours=6)
        account = MagicMock(updated_at=timezone.now() - timedelta(hours=12))
        self.assertFalse(should_skip_account_recent(account, cutoff))

    def test_build_items_marks_recent_as_skipped(self):
        cutoff = timezone.now() - timedelta(hours=3)
        fresh = MagicMock(
            id=1,
            platform="tiktok",
            username="fresh",
            updated_at=timezone.now(),
        )
        stale = MagicMock(
            id=2,
            platform="tiktok",
            username="stale",
            updated_at=timezone.now() - timedelta(days=2),
        )
        items, skip_n = build_initial_run_detail_items(
            [fresh, stale],
            skip_recent_hours=3,
            cutoff=cutoff,
        )
        self.assertEqual(skip_n, 1)
        self.assertEqual(items[0]["status"], "skipped")
        self.assertEqual(items[1]["status"], "queued")

    def test_apply_upfront_completes_queue_slots(self):
        cutoff = timezone.now() - timedelta(hours=2)
        accounts = [
            MagicMock(
                id=10,
                platform="tiktok",
                username="a",
                updated_at=timezone.now(),
            ),
            MagicMock(
                id=11,
                platform="tiktok",
                username="b",
                updated_at=timezone.now() - timedelta(days=1),
            ),
        ]
        q = ParallelAccountQueue(2, {"tiktok": 1})
        n = apply_upfront_skip_recent(
            accounts,
            cutoff=cutoff,
            skip_recent_hours=2,
            account_queue=q,
        )
        self.assertEqual(n, 1)
        idx = q.claim(lambda i: accounts[i].platform, wait=False)
        self.assertEqual(idx, 1)
