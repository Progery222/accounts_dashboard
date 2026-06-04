from django.test import SimpleTestCase

from accounts.facebook_refresh_lane import (
    FACEBOOK_DEDICATED_WORKER_SLOT,
    allocate_worker_slot,
    batch_has_facebook,
    begin_facebook_batch,
    end_facebook_batch,
    executor_thread_counts,
    platform_claim_filter,
    try_mark_facebook_account_started,
)
from accounts.models import Account, Platform
from accounts.parallel_account_queue import ParallelAccountQueue


class FacebookRefreshLaneTests(SimpleTestCase):
    def test_executor_thread_counts(self):
        self.assertEqual(executor_thread_counts(6, has_facebook=False), (0, 6))
        self.assertEqual(executor_thread_counts(6, has_facebook=True), (1, 5))
        self.assertEqual(executor_thread_counts(1, has_facebook=True), (1, 1))

    def test_platform_claim_filter(self):
        fb_only = platform_claim_filter(facebook_lane=True)
        other = platform_claim_filter(facebook_lane=False)
        self.assertTrue(fb_only(Platform.FACEBOOK))
        self.assertFalse(fb_only(Platform.TIKTOK))
        self.assertFalse(other(Platform.FACEBOOK))
        self.assertTrue(other(Platform.TIKTOK))

    def test_dedicated_slot_is_zero(self):
        self.assertEqual(FACEBOOK_DEDICATED_WORKER_SLOT, 0)
        m: dict[int, int] = {}
        import threading

        lock = threading.Lock()
        self.assertEqual(
            allocate_worker_slot(facebook_lane=True, thread_slot_map=m, thread_slot_lock=lock),
            0,
        )
        self.assertEqual(
            allocate_worker_slot(facebook_lane=False, thread_slot_map=m, thread_slot_lock=lock),
            1,
        )

    def test_no_duplicate_facebook_account_in_batch(self):
        begin_facebook_batch()
        try:
            self.assertTrue(try_mark_facebook_account_started(42))
            self.assertFalse(try_mark_facebook_account_started(42))
        finally:
            end_facebook_batch()

    def test_queue_fb_lane_skips_non_facebook(self):
        platforms = ["facebook", "tiktok", "facebook"]
        q = ParallelAccountQueue(len(platforms), {"facebook": 1, "tiktok": 2})
        fb_filter = platform_claim_filter(facebook_lane=True)
        i0 = q.claim(lambda i: platforms[i], platform_filter=fb_filter)
        self.assertEqual(i0, 0)
        self.assertIsNone(q.claim(lambda i: platforms[i], platform_filter=fb_filter, wait=False))
        q.finish(0, "facebook")
        i2 = q.claim(lambda i: platforms[i], platform_filter=fb_filter)
        self.assertEqual(i2, 2)

    def test_batch_has_facebook(self):
        acc = Account(platform=Platform.FACEBOOK, username="x")
        self.assertTrue(batch_has_facebook([acc]))
