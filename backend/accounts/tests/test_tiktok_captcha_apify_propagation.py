from unittest.mock import patch

from django.test import SimpleTestCase

from platforms.tiktok.service import _run_worker


class TikTokCaptchaPropagationTests(SimpleTestCase):
    @patch("platforms.tiktok.service.call_worker")
    def test_run_worker_propagates_captcha_stall(self, mock_call_worker) -> None:
        mock_call_worker.side_effect = ValueError(
            "TikTok: SadCaptcha не снял капчу за отведённое время. "
            "Проверьте баланс/ключ на sadcaptcha.com."
        )
        with self.assertRaises(ValueError) as ctx:
            _run_worker("https://www.tiktok.com/@demo")
        self.assertIn("SadCaptcha", str(ctx.exception))

    @patch("platforms.tiktok.service.call_worker")
    def test_run_worker_swallows_other_errors(self, mock_call_worker) -> None:
        mock_call_worker.side_effect = ValueError("network glitch")
        items, stats = _run_worker("https://www.tiktok.com/@demo")
        self.assertEqual(items, [])
        self.assertEqual(stats, {})
