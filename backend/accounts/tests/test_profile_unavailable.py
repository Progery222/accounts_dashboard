from django.test import SimpleTestCase

from platforms.profile_unavailable import (
    PROFILE_UNAVAILABLE_MARK,
    is_profile_unavailable_error,
    user_visible_profile_unavailable_error,
)


class ProfileUnavailableDetectionTests(SimpleTestCase):
    def test_detects_prefixed_error(self):
        self.assertTrue(is_profile_unavailable_error(f"{PROFILE_UNAVAILABLE_MARK}Instagram @u: профиль не найден"))

    def test_detects_common_unavailable_markers(self):
        self.assertTrue(is_profile_unavailable_error("Profile not found"))
        self.assertTrue(is_profile_unavailable_error("Аккаунт заблокирован площадкой"))
        self.assertTrue(is_profile_unavailable_error("User is suspended"))

    def test_ignores_non_unavailable_errors(self):
        self.assertFalse(is_profile_unavailable_error("Timeout while waiting for selector"))

    def test_trustworthy_rejection_message_not_profile_gone(self):
        from accounts.views import _is_refresh_stats_rejection

        msg = (
            "Данные выглядят как ошибка или недоступность: нулевые метрики при ненулевых в базе "
            "или профиль помечен недоступным. Обновление не применено."
        )
        self.assertTrue(_is_refresh_stats_rejection(ValueError(msg)))
        self.assertFalse(is_profile_unavailable_error(msg))

    def test_user_visible_message_strips_prefix_only(self):
        raw = f"{PROFILE_UNAVAILABLE_MARK}Threads @abc: профиль недоступен"
        self.assertEqual(
            user_visible_profile_unavailable_error(raw),
            "Threads @abc: профиль недоступен",
        )
