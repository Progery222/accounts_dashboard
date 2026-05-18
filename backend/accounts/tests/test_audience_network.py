from django.test import SimpleTestCase

from accounts.audience import _sanitize_follower_network


class AudienceFollowerNetworkSanitizeTests(SimpleTestCase):
    def test_sanitize_caps_length_and_coerces_counts(self):
        tail = [{"username": f"u{i}", "bio": "", "follower_count": 1} for i in range(120)]
        raw = [
            {"username": "alpha", "bio": "b", "follower_count": "12", "following_count": 3},
            "skip",
            {"username": "", "bio": "x"},
        ] + tail
        out = _sanitize_follower_network(raw)
        self.assertEqual(len(out), 100)
        self.assertEqual(out[0]["username"], "alpha")
        self.assertEqual(out[0]["follower_count"], 12)
        self.assertEqual(out[0]["following_count"], 3)
