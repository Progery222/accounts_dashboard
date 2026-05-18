"""Unit-тесты логики применения лайков Reels (без Playwright)."""
import importlib.util
import unittest
from pathlib import Path

_worker_path = Path(__file__).resolve().parents[1] / "worker.py"
_spec = importlib.util.spec_from_file_location("fb_worker", _worker_path)
_worker = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(_worker)

_should_apply = _worker._facebook_detail_likes_should_apply


class FacebookReelLikeApplyTests(unittest.TestCase):
    def test_confirmed_zero_always_applies(self):
        self.assertTrue(_should_apply(0, 162, 16_000, confirmed=True))
        self.assertTrue(_should_apply(0, 0, 0, confirmed=True))

    def test_unconfirmed_zero_never_applies(self):
        self.assertFalse(_should_apply(0, 5, 100, confirmed=False))

    def test_unconfirmed_positive_increases(self):
        self.assertTrue(_should_apply(9, 0, 16_000, confirmed=False))
        self.assertFalse(_should_apply(5, 10, 100, confirmed=False))

    def test_phantom_correction_without_confirmed(self):
        self.assertTrue(_should_apply(9, 16_000, 16_000, confirmed=False))


if __name__ == "__main__":
    unittest.main()
