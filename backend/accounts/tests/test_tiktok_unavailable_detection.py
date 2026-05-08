from django.test import SimpleTestCase

from platforms.tiktok.service import _is_tiktok_profile_unavailable_html


class TikTokUnavailableDetectionTests(SimpleTestCase):
    def test_detects_not_found_phrase(self):
        html = "<html><body><h1>Couldn't find this account</h1></body></html>"
        self.assertTrue(_is_tiktok_profile_unavailable_html(html))

    def test_detects_not_found_phrase_with_unicode_apostrophe(self):
        html = "<html><body><title>Couldn’t find this account</title></body></html>"
        self.assertTrue(_is_tiktok_profile_unavailable_html(html))

    def test_ignores_regular_profile_html(self):
        html = "<html><head><title>TikTok</title></head><body>Followers 10K</body></html>"
        self.assertFalse(_is_tiktok_profile_unavailable_html(html))
