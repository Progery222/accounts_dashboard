from django.test import SimpleTestCase, override_settings

from platforms.instagram.posts_meta import annotate_instagram_posts_payload, instagram_max_posts


class InstagramPostsMetaTests(SimpleTestCase):
    @override_settings(INSTAGRAM_MAX_POSTS=80)
    def test_default_max_posts(self):
        self.assertEqual(instagram_max_posts(), 80)

    def test_authoritative_when_enough_posts(self):
        payload = annotate_instagram_posts_payload(
            {
                "post_count": 50,
                "_posts": [{"external_id": f"p{i}"} for i in range(45)],
            },
        )
        self.assertTrue(payload["_posts_authoritative"])

    def test_not_authoritative_when_too_few_posts(self):
        payload = annotate_instagram_posts_payload(
            {
                "post_count": 100,
                "_posts": [{"external_id": "abc"} for _ in range(12)],
            },
        )
        self.assertFalse(payload["_posts_authoritative"])
        self.assertTrue(payload.get("_partial"))
