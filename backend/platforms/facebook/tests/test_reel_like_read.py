"""Unit-тесты логики применения лайков Reels (без Playwright)."""
import importlib.util
import unittest
from pathlib import Path

_worker_path = Path(__file__).resolve().parents[1] / "worker.py"
_spec = importlib.util.spec_from_file_location("fb_worker", _worker_path)
_worker = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(_worker)

_should_apply = _worker._facebook_detail_likes_should_apply
_parse_page_likes = _worker._parse_facebook_page_like_count


class FacebookReelLikeApplyTests(unittest.TestCase):
    def test_confirmed_zero_always_applies(self):
        self.assertTrue(_should_apply(0, 162, 16_000, confirmed=True))
        self.assertTrue(_should_apply(0, 0, 0, confirmed=True))

    def test_unconfirmed_zero_never_applies(self):
        self.assertFalse(_should_apply(0, 5, 100, confirmed=False))

    def test_unconfirmed_positive_increases(self):
        self.assertTrue(_should_apply(9, 0, 16_000, confirmed=False))
        self.assertFalse(_should_apply(5, 10, 100, confirmed=False))

    def test_phantom_correction_without_confirmed(self):
        self.assertTrue(_should_apply(9, 16_000, 16_000, confirmed=False))

    def test_heuristics_skip_confirmed_likes(self):
        posts = [
            {"view_count": 2700, "like_count": 2700, "like_count_confirmed": True},
            {"view_count": 1400, "like_count": 1400, "like_count_confirmed": False},
        ]
        _worker._facebook_zero_like_if_equals_views(posts)
        self.assertEqual(posts[0]["like_count"], 2700)
        self.assertEqual(posts[1]["like_count"], 0)

        confirmed = [
            {"view_count": 2700, "like_count": 1400, "like_count_confirmed": True},
            {"view_count": 1400, "like_count": 10},
        ]
        _worker._facebook_zero_likes_if_like_is_other_post_view_count(confirmed)
        self.assertEqual(confirmed[0]["like_count"], 1400)

        collided = [
            {"view_count": 2700, "like_count": 1400},
            {"view_count": 1400, "like_count": 10},
        ]
        _worker._facebook_zero_likes_if_like_is_other_post_view_count(collided)
        self.assertEqual(collided[0]["like_count"], 0)

    def test_dedupe_skips_confirmed(self):
        posts = [
            {"view_count": 100, "like_count": 50, "like_count_confirmed": True},
            {"view_count": 200, "like_count": 50},
            {"view_count": 300, "like_count": 50},
            {"view_count": 400, "like_count": 50},
        ]
        _worker._facebook_dedupe_phantom_likes(posts)
        self.assertEqual(posts[0]["like_count"], 50)
        self.assertEqual(posts[1]["like_count"], 0)
        self.assertEqual(posts[2]["like_count"], 0)
        self.assertEqual(posts[3]["like_count"], 0)


class FacebookPageLikeParsingTests(unittest.TestCase):
    def test_reads_russian_meta_description_format(self):
        bio = 'Arena Sports Platform. Отметки "Нравится": 7 224 Обсуждают: 3 948.'
        self.assertEqual(_parse_page_likes("", bio), 7_224)

    def test_explicit_page_likes_take_precedence(self):
        self.assertEqual(
            _parse_page_likes("7,3 тыс.", 'Отметки "Нравится": 7 224'),
            7_300,
        )

    def test_unrelated_bio_number_is_ignored(self):
        self.assertEqual(_parse_page_likes("", "Sports platform founded in 2024"), 0)


class FacebookFriendsAsFollowersTests(unittest.TestCase):
    def test_friends_fill_empty_followers(self):
        fn = _worker._follower_count_with_friends_fallback
        self.assertEqual(fn(0, 342), 342)
        self.assertEqual(fn(0, 1_200), 1_200)

    def test_real_followers_win_over_friends(self):
        fn = _worker._follower_count_with_friends_fallback
        self.assertEqual(fn(7_200, 342), 7_200)
        self.assertEqual(fn(50, 0), 50)

    def test_both_empty_stays_zero(self):
        self.assertEqual(_worker._follower_count_with_friends_fallback(0, 0), 0)

    def test_merge_keeps_max_friends(self):
        merged = _worker._merge_facebook_profile_js(
            {"followers": "", "friends": "120", "pageLikes": ""},
            {"followers": "", "friends": "340", "pageLikes": ""},
        )
        self.assertEqual(merged.get("friends"), "340")

    def test_parse_friends_from_html_json(self):
        html = '{"friend_count":512,"name":"Test"}'
        self.assertEqual(_worker._parse_friends_from_html(html), 512)

    def test_parse_friends_from_html_skips_mutual(self):
        html = "У вас 12 общих друзей и friend_count:0"
        # mutual phrase nearby should not pick 12 from Russian phrase if only mutual
        n = _worker._parse_friends_from_html("у вас 12 общих друзей")
        self.assertEqual(n, 0)

    def test_numeric_personal_profile(self):
        self.assertTrue(_worker._facebook_is_numeric_personal_profile("61593723673054"))
        self.assertFalse(_worker._facebook_is_numeric_personal_profile("bcs.arena"))


if __name__ == "__main__":
    unittest.main()
