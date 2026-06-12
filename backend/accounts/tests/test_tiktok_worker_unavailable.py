from django.test import SimpleTestCase

from platforms.tiktok.worker import (
    _parse_user_detail_availability,
    _profile_stats_from_user_detail,
    _should_mark_tiktok_profile_unavailable,
    _tiktok_profile_missing_error,
)


class TikTokWorkerUnavailableProbeTests(SimpleTestCase):
    def test_dom_not_found_without_profile_signals(self):
        self.assertTrue(
            _should_mark_tiktok_profile_unavailable(
                body_text="Couldn't find this account",
                title="TikTok",
                og_title="",
                username="john.lander27",
                has_avatar=False,
                has_stats=False,
                has_post_items=False,
            )
        )

    def test_dom_not_found_with_title_handle_is_not_unavailable(self):
        self.assertFalse(
            _should_mark_tiktok_profile_unavailable(
                body_text="Couldn't find this account",
                title="John Lander (@john.lander27) | TikTok",
                og_title="",
                username="john.lander27",
                has_avatar=False,
                has_stats=False,
                has_post_items=False,
            )
        )

    def test_user_detail_unique_id_means_found(self):
        state = _parse_user_detail_availability(
            {
                "userInfo": {
                    "user": {"uniqueId": "john.lander27", "secUid": "abc"},
                    "stats": {"followerCount": 1},
                }
            },
            "john.lander27",
        )
        self.assertEqual(state, "found")

    def test_user_detail_gone_status_means_missing(self):
        state = _parse_user_detail_availability(
            {"statusCode": 10202, "userInfo": {"user": {}}},
            "john.lander27",
        )
        self.assertEqual(state, "missing")

    def test_profile_missing_error_has_mark(self):
        err = _tiktok_profile_missing_error("gone.user")
        self.assertTrue(str(err).startswith("PROFILE_UNAVAILABLE|"))
        self.assertIn("@gone.user", str(err))

    def test_empty_user_detail_is_unknown_not_missing(self):
        state = _parse_user_detail_availability(
            {"userInfo": {"user": {}}},
            "john.lander27",
        )
        self.assertEqual(state, "unknown")

    def test_profile_stats_from_user_detail(self):
        stats = _profile_stats_from_user_detail(
            {
                "userInfo": {
                    "user": {"avatarLarger": "https://cdn.example/a.jpg"},
                    "stats": {"followerCount": 1, "heartCount": 8},
                }
            }
        )
        self.assertEqual(stats["follower_text"], "1")
        self.assertEqual(stats["like_text"], "8")
        self.assertEqual(stats["avatar_url"], "https://cdn.example/a.jpg")
