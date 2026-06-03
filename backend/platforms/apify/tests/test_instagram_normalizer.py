from django.test import SimpleTestCase

from platforms.apify.normalizers.instagram import normalize_instagram


class InstagramNormalizerAvatarTests(SimpleTestCase):
    def test_omits_avatar_url_when_profile_has_no_picture(self):
        payload = normalize_instagram(
            [{"username": "yllazenera", "fullName": "yylla zen"}],
            [],
            profile_succeeded=True,
            posts_succeeded=True,
        )
        self.assertNotIn("avatar_url", payload)

    def test_includes_avatar_url_when_present(self):
        payload = normalize_instagram(
            [
                {
                    "username": "test",
                    "profilePicUrl": "https://cdn.example/avatar.jpg",
                }
            ],
            [],
            profile_succeeded=True,
            posts_succeeded=True,
        )
        self.assertEqual(payload["avatar_url"], "https://cdn.example/avatar.jpg")
