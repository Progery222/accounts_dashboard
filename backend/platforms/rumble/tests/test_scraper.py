from unittest.mock import patch

from django.test import SimpleTestCase

from platforms.rumble.scraper import (
    fetch_rumble_profile,
    playwright_fallback_enabled,
    skip_playwright_prewarm,
)


class RumbleScraperPlaywrightPolicyTests(SimpleTestCase):
    def test_playwright_fallback_off_by_default(self):
        with patch.dict("os.environ", {"RUMBLE_PLAYWRIGHT_FALLBACK": ""}, clear=False):
            self.assertFalse(playwright_fallback_enabled())

    def test_skip_prewarm_by_default(self):
        with patch.dict("os.environ", {"RUMBLE_PLAYWRIGHT_FALLBACK": "0"}, clear=False):
            self.assertTrue(skip_playwright_prewarm())

    def test_no_skip_prewarm_when_fallback_enabled(self):
        with patch.dict("os.environ", {"RUMBLE_PLAYWRIGHT_FALLBACK": "1"}, clear=False):
            self.assertFalse(skip_playwright_prewarm())

    def test_fetch_skips_worker_when_fs_fails_and_fallback_disabled(self):
        with patch.dict("os.environ", {"RUMBLE_PLAYWRIGHT_FALLBACK": "0"}, clear=False), patch(
            "platforms.rumble.flaresolverr_client.is_available",
            return_value=True,
        ), patch(
            "platforms.rumble.flaresolverr_client.fetch_profile",
            side_effect=ValueError("не найден"),
        ), patch(
            "platforms.rumble.scraper._run_worker",
        ) as worker_mock:
            with self.assertRaises(ValueError) as ctx:
                fetch_rumble_profile("starrlanderboy")
            self.assertIn("FlareSolverr", str(ctx.exception))
            worker_mock.assert_not_called()

    def test_fetch_skips_worker_when_fs_unavailable_and_fallback_disabled(self):
        with patch.dict("os.environ", {"RUMBLE_PLAYWRIGHT_FALLBACK": "0"}, clear=False), patch(
            "platforms.rumble.flaresolverr_client.is_available",
            return_value=False,
        ), patch(
            "platforms.rumble.scraper._run_worker",
        ) as worker_mock:
            with self.assertRaises(ValueError) as ctx:
                fetch_rumble_profile("starrlanderboy")
            self.assertIn("FlareSolverr недоступен", str(ctx.exception))
            worker_mock.assert_not_called()

    def test_fetch_uses_worker_when_fallback_enabled_and_fs_down(self):
        with patch.dict("os.environ", {"RUMBLE_PLAYWRIGHT_FALLBACK": "1"}, clear=False), patch(
            "platforms.rumble.flaresolverr_client.is_available",
            return_value=False,
        ), patch(
            "platforms.rumble.scraper._run_worker",
            return_value={"username": "ok", "_posts": []},
        ) as worker_mock:
            data = fetch_rumble_profile("tobiasreed88")
            worker_mock.assert_called_once_with("tobiasreed88")
            self.assertEqual(data["username"], "ok")

    def test_call_worker_blocks_rumble_without_fallback(self):
        from pathlib import Path

        from platforms.worker_pool import call_worker

        worker = Path(__file__).resolve().parents[1] / "worker.py"
        with patch.dict("os.environ", {"RUMBLE_PLAYWRIGHT_FALLBACK": "0"}, clear=False):
            with self.assertRaises(ValueError) as ctx:
                call_worker(worker, {"username": "x"})
        self.assertIn("FlareSolverr", str(ctx.exception))
