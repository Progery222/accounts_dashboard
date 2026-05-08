from django.test import SimpleTestCase

from platforms.x.scraper import _message_indicates_x_profile_unavailable


class XUnavailableDetectionTests(SimpleTestCase):
    def test_detects_x_account_does_not_exist_message(self):
        msg = "This account doesn’t exist. Try searching for another."
        self.assertTrue(_message_indicates_x_profile_unavailable(msg))

    def test_ignores_connection_error_message(self):
        msg = "X не загрузился — проверь подключение."
        self.assertFalse(_message_indicates_x_profile_unavailable(msg))
