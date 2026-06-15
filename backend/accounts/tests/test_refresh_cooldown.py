from django.test import SimpleTestCase

from accounts.models import Platform
from accounts.views import _refresh_all_cooldown_seconds, _refresh_all_delay_seconds
from platforms.profile_unavailable import PROFILE_UNAVAILABLE_MARK


class RefreshCooldownTests(SimpleTestCase):
    def test_profile_unavailable_skips_tiktok_cooldown(self):
        account = type(
            "Acc",
            (),
            {"platform": Platform.TIKTOK, "username": "gone", "profile_unavailable": True},
        )()
        self.assertEqual(_refresh_all_cooldown_seconds(account), 0.0)
        self.assertGreater(_refresh_all_delay_seconds(account), 0.0)

    def test_not_found_error_skips_cooldown(self):
        account = type(
            "Acc",
            (),
            {"platform": Platform.TIKTOK, "username": "gone", "profile_unavailable": False},
        )()
        exc = ValueError(
            f"{PROFILE_UNAVAILABLE_MARK}TikTok @gone: профиль не найден или недоступен на площадке."
        )
        self.assertEqual(_refresh_all_cooldown_seconds(account, exc=exc), 0.0)

    def test_success_keeps_platform_delay(self):
        account = type(
            "Acc",
            (),
            {"platform": Platform.TIKTOK, "username": "ok", "profile_unavailable": False},
        )()
        self.assertGreater(_refresh_all_cooldown_seconds(account), 0.0)

    def test_rumble_default_delay(self):
        account = type(
            "Acc",
            (),
            {"platform": Platform.RUMBLE, "username": "ok", "profile_unavailable": False},
        )()
        delay = _refresh_all_delay_seconds(account)
        self.assertGreaterEqual(delay, 20.0)
        self.assertLessEqual(delay, 40.0)
