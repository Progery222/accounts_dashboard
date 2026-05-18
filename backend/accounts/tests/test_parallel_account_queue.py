import threading
import time

from django.test import SimpleTestCase

from accounts.parallel_account_queue import ParallelAccountQueue


class ParallelAccountQueueTests(SimpleTestCase):
    def test_claim_skips_blocked_platform_head(self):
        platforms = ["threads"] * 3 + ["youtube", "youtube"]
        q = ParallelAccountQueue(len(platforms), {"threads": 1, "youtube": 2})
        claimed: list[int] = []

        def get_platform(i: int) -> str:
            return platforms[i]

        i0 = q.claim(get_platform)
        self.assertEqual(i0, 0)
        i1 = q.claim(get_platform)
        self.assertEqual(i1, 3)
        i2 = q.claim(get_platform)
        self.assertEqual(i2, 4)
        self.assertIsNone(q.claim(get_platform, wait=False))

        q.finish(0, "threads")
        i3 = q.claim(get_platform)
        self.assertIn(i3, (1, 2))
        q.finish(i3, "threads")
        i4 = q.claim(get_platform)
        self.assertEqual(i4, 1 if i3 == 2 else 2)

    def test_cooldown_skips_platform_until_ready(self):
        q = ParallelAccountQueue(2, {"x": 1})
        q.set_platform_cooldown("x", 60.0)
        self.assertIsNone(q.claim(lambda i: "x", wait=False))
        with q._lock:
            q._cooldown_until["x"] = 0.0
        self.assertEqual(q.claim(lambda i: "x", wait=False), 0)
