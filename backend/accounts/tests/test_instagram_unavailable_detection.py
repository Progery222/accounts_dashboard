from django.test import SimpleTestCase

from platforms.instagram.scraper import _message_indicates_removed_instagram_profile


class InstagramUnavailableDetectionTests(SimpleTestCase):
    def test_detects_instagram_not_available_message(self):
        msg = "Sorry, this page isn't available. The link you followed may be broken."
        self.assertTrue(_message_indicates_removed_instagram_profile(msg))

    def test_ignores_unrelated_worker_error(self):
        msg = "Instagram требует авторизации — войдите в аккаунт в настройках и повторите."
        self.assertFalse(_message_indicates_removed_instagram_profile(msg))
