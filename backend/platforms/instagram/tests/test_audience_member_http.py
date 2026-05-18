from django.test import SimpleTestCase

from platforms.instagram.audience_member_http import (
    _parse_ig_counts_from_meta_description,
    parse_instagram_profile_html,
)


class InstagramAudienceMemberHttpTest(SimpleTestCase):
    def test_meta_description_counts(self):
        posts, followers, following = _parse_ig_counts_from_meta_description(
            "4 posts, 378 followers, 1107 following - See photos and videos from Arvind"
        )
        self.assertEqual(posts, 4)
        self.assertEqual(followers, 378)
        self.assertEqual(following, 1107)

    def test_parse_html_meta_description_profile(self):
        html = """
        <html><head>
        <meta property="og:title" content="Arvind Arvind K (@arvindkumarrajpura00) • Instagram photos and videos" />
        <meta name="description" content="4 posts, 378 followers, 1107 following - See Instagram photos and videos from Arvind Arvind K (@arvindkumarrajpura00)" />
        </head><body></body></html>
        """
        out = parse_instagram_profile_html(html)
        self.assertEqual(out["follower_count"], 378)
        self.assertEqual(out["following_count"], 1107)
        self.assertIn("Arvind", out["display_name"])
        self.assertTrue(out["_ok"])
