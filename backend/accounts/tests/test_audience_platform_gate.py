import threading
import time

from django.test import SimpleTestCase

from accounts.audience_platform_gate import audience_platform_slot


class AudiencePlatformGateTests(SimpleTestCase):
    def test_same_platform_serializes(self):
        order: list[str] = []
        lock = threading.Lock()

        def worker(tag: str) -> None:
            with audience_platform_slot("tiktok"):
                with lock:
                    order.append(f"{tag}-in")
                time.sleep(0.05)
                with lock:
                    order.append(f"{tag}-out")

        t1 = threading.Thread(target=worker, args=("a",))
        t2 = threading.Thread(target=worker, args=("b",))
        t1.start()
        t2.start()
        t1.join(timeout=5)
        t2.join(timeout=5)
        self.assertEqual(order, ["a-in", "a-out", "b-in", "b-out"])

    def test_different_platforms_do_not_block_each_other(self):
        inside: dict[str, int] = {"tiktok": 0, "instagram": 0}
        guard = threading.Lock()
        both = threading.Event()

        def worker(platform: str) -> None:
            with audience_platform_slot(platform):
                with guard:
                    inside[platform] += 1
                    if inside["tiktok"] > 0 and inside["instagram"] > 0:
                        both.set()
                time.sleep(0.08)
                with guard:
                    inside[platform] -= 1

        t1 = threading.Thread(target=worker, args=("tiktok",))
        t2 = threading.Thread(target=worker, args=("instagram",))
        t1.start()
        t2.start()
        t1.join(timeout=5)
        t2.join(timeout=5)
        self.assertTrue(both.wait(timeout=2))
