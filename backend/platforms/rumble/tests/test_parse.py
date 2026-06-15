from pathlib import Path

from django.test import SimpleTestCase

from platforms.rumble.parse import extract_thumbnail_posts, normalize_username, profile_from_html


class RumbleParseTests(SimpleTestCase):
    def test_normalize_user_url(self):
        self.assertEqual(normalize_username("https://rumble.com/user/datezaddy12"), "datezaddy12")
        self.assertEqual(normalize_username("https://rumble.com/datezaddy12"), "datezaddy12")

    def test_thumbnail_posts_from_fixture(self):
        html_path = Path(__file__).resolve().parents[3] / "var" / "_rumble_user_datezaddy12_feed.html"
        if not html_path.exists():
            self.skipTest("fixture HTML not present")
        html = html_path.read_text(encoding="utf-8")
        posts = extract_thumbnail_posts(html)
        self.assertEqual(len(posts), 1)
        self.assertEqual(posts[0]["external_id"], "438302490")
        self.assertEqual(posts[0]["post_url"], "https://rumble.com/shorts/v7b50de")
        self.assertEqual(posts[0]["view_count"], 10)

    def test_profile_from_fixture(self):
        base = Path(__file__).resolve().parents[3] / "var"
        about = base / "_rumble_user_datezaddy12_about.html"
        feed = base / "_rumble_user_datezaddy12_feed.html"
        if not about.exists() or not feed.exists():
            self.skipTest("fixture HTML not present")
        payload = profile_from_html(
            username="datezaddy12",
            about_html=about.read_text(encoding="utf-8"),
            feed_html=feed.read_text(encoding="utf-8"),
        )
        self.assertEqual(payload["display_name"], "datezaddy12")
        self.assertEqual(payload["view_count"], 10)
        self.assertEqual(payload["post_count"], 1)
        self.assertEqual(len(payload["_posts"]), 1)

    def test_thumbnail_merge_footer_views(self):
        html = """
        <rum-video-thumbnail video-id="438302496" title="A" src="https://x/y.jpg"
          url="https://rumble.com/shorts/abc123"></rum-video-thumbnail>
        <rum-video-thumbnail-footer video-id="438302496" views="15" time="2026-01-01"
          url="https://rumble.com/shorts/abc123" title="A"></rum-video-thumbnail-footer>
        """
        posts = extract_thumbnail_posts(html)
        self.assertEqual(len(posts), 1)
        self.assertEqual(posts[0]["view_count"], 15)

    def test_thumbnail_footer_first_without_views(self):
        html = """
        <rum-video-thumbnail-footer video-id="438302496" views="15"
          url="https://rumble.com/shorts/abc123" title="A"></rum-video-thumbnail-footer>
        <rum-video-thumbnail video-id="438302496" title="A" src="https://x/y.jpg"
          url="https://rumble.com/shorts/abc123"></rum-video-thumbnail>
        """
        posts = extract_thumbnail_posts(html)
        self.assertEqual(posts[0]["view_count"], 15)
