from django.test import SimpleTestCase

from platforms.tiktok.service import _filter_profile_items, _videos_from_profile_html


class TikTokProfileItemsTests(SimpleTestCase):
    def test_filter_keeps_items_without_author(self) -> None:
        items = [{"id": "1"}, {"id": "2", "author": {"uniqueId": "other"}}]
        out = _filter_profile_items(items, "tobi.reed2")
        self.assertEqual([i["id"] for i in out], ["1"])

    def test_videos_from_profile_html_extracts_ids(self) -> None:
        html = '<a href="https://www.tiktok.com/@tobi.reed2/video/7123456789012345678">x</a>'
        out = _videos_from_profile_html(html, "tobi.reed2")
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["id"], "7123456789012345678")

    def test_filter_keeps_matching_author(self) -> None:
        items = [{"id": "9", "author": {"uniqueId": "tobi.reed2"}}]
        out = _filter_profile_items(items, "tobi.reed2")
        self.assertEqual([i["id"] for i in out], ["9"])
