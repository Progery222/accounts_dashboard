from django.test import SimpleTestCase

from platforms.tiktok.captcha_batch import (
    TikTokRefreshBatchGuard,
    is_tiktok_captcha_stall_error,
)


class TikTokCaptchaBatchTests(SimpleTestCase):
    def test_detects_captcha_timeout(self) -> None:
        exc = ValueError(
            "TikTok: время ожидания капчи истекло. Пройдите проверку в открытом окне Chrome."
        )
        self.assertTrue(is_tiktok_captcha_stall_error(exc))

    def test_detects_sadcaptcha_timeout(self) -> None:
        exc = ValueError("TikTok: SadCaptcha не снял капчу за отведённое время.")
        self.assertTrue(is_tiktok_captcha_stall_error(exc))

    def test_ignores_unrelated(self) -> None:
        self.assertFalse(is_tiktok_captcha_stall_error(ValueError("profile not found")))

    def test_guard_trips_once(self) -> None:
        g = TikTokRefreshBatchGuard()
        self.assertFalse(g.is_tripped())
        g.trip("первая ошибка")
        self.assertTrue(g.is_tripped())
        self.assertIn("первая", g.error_detail())
        g.trip("вторая")
        self.assertIn("первая", g.error_detail())
