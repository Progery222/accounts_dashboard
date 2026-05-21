from django.test import SimpleTestCase

from platforms.facebook.profile_meta import (
    is_junk_facebook_display_name,
    is_usable_facebook_avatar_url,
    sanitize_facebook_display_name,
)


class FacebookProfileMetaTests(SimpleTestCase):
    def test_junk_display_names(self):
        for name in ("Уведомления", "Notifications", "Поиск", "123456", ""):
            self.assertTrue(is_junk_facebook_display_name(name))
        self.assertFalse(is_junk_facebook_display_name("Ylla Zenx"))

    def test_sanitize_clears_junk(self):
        self.assertEqual(sanitize_facebook_display_name("Уведомления"), "")
        self.assertEqual(sanitize_facebook_display_name("Real Page"), "Real Page")

    def test_avatar_usability(self):
        self.assertFalse(is_usable_facebook_avatar_url(""))
        self.assertFalse(
            is_usable_facebook_avatar_url(
                "https://scontent.xx.fbcdn.net/v/p16x16/1.png"
            )
        )
        self.assertTrue(
            is_usable_facebook_avatar_url(
                "https://scontent.xx.fbcdn.net/v/t39.30808-6/123.jpg"
            )
        )
