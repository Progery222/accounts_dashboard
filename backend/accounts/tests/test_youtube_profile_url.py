"""Канонизация YouTube username (кириллический @handle vs /channel/UC…)."""
from django.test import SimpleTestCase

from platforms.youtube.profile_url import canonical_youtube_username_for_storage


class YoutubeProfileUrlTests(SimpleTestCase):
    def test_cyrillic_handle_url_without_scheme(self):
        self.assertEqual(
            canonical_youtube_username_for_storage("www.youtube.com/@АлесяБут-х2н"),
            "АлесяБут-х2н",
        )

    def test_cyrillic_handle_full_url(self):
        self.assertEqual(
            canonical_youtube_username_for_storage("https://www.youtube.com/@АлесяБут-х2н"),
            "АлесяБут-х2н",
        )

    def test_cyrillic_handle_with_videos_suffix(self):
        self.assertEqual(
            canonical_youtube_username_for_storage(
                "https://www.youtube.com/@АлесяБут-х2н/videos"
            ),
            "АлесяБут-х2н",
        )

    def test_bare_handle(self):
        self.assertEqual(canonical_youtube_username_for_storage("@АлесяБут-х2н"), "АлесяБут-х2н")
        self.assertEqual(canonical_youtube_username_for_storage("АлесяБут-х2н"), "АлесяБут-х2н")

    def test_channel_id_url_kept_as_id(self):
        self.assertEqual(
            canonical_youtube_username_for_storage(
                "https://www.youtube.com/channel/UCn-t5Z16uoP60hkWQQ7d_Tg"
            ),
            "UCn-t5Z16uoP60hkWQQ7d_Tg",
        )

    def test_percent_encoded_handle(self):
        raw = "https://www.youtube.com/@%D0%90%D0%BB%D0%B5%D1%81%D1%8F%D0%91%D1%83%D1%82-%D1%852%D0%BD"
        self.assertEqual(canonical_youtube_username_for_storage(raw), "АлесяБут-х2н")

    def test_does_not_convert_handle_to_channel_id(self):
        # Канонизация только парсит URL; UC… не подставляется из handle.
        self.assertNotEqual(
            canonical_youtube_username_for_storage("www.youtube.com/@АлесяБут-х2н"),
            "UCn-t5Z16uoP60hkWQQ7d_Tg",
        )
