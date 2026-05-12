"""Разбор ссылок Facebook (profile.php?id=… и vanity)."""
from django.test import SimpleTestCase

from platforms.facebook.profile_url import (
    canonical_facebook_username_for_storage,
    normalize_facebook_profile_input,
)


class FacebookProfileUrlTests(SimpleTestCase):
    def test_profile_php_full_url(self):
        nav, mbasic, base = normalize_facebook_profile_input(
            "https://www.facebook.com/profile.php?id=61589216603998"
        )
        self.assertEqual(nav, "https://www.facebook.com/profile.php?id=61589216603998")
        self.assertEqual(
            mbasic,
            "https://mbasic.facebook.com/profile.php?id=61589216603998&v=timeline",
        )
        self.assertEqual(base, "https://www.facebook.com/61589216603998")

    def test_bare_numeric_id(self):
        nav, mbasic, base = normalize_facebook_profile_input("61589216603998")
        self.assertEqual(nav, "https://www.facebook.com/profile.php?id=61589216603998")
        self.assertIn("profile.php?id=61589216603998", mbasic)
        self.assertEqual(base, "https://www.facebook.com/61589216603998")

    def test_profile_php_path_only(self):
        nav, _, _ = normalize_facebook_profile_input("profile.php?id=61589216603998")
        self.assertEqual(nav, "https://www.facebook.com/profile.php?id=61589216603998")

    def test_vanity_slug(self):
        nav, mbasic, base = normalize_facebook_profile_input("SomePageName")
        self.assertEqual(nav, "https://www.facebook.com/SomePageName")
        self.assertEqual(mbasic, "https://mbasic.facebook.com/SomePageName?v=timeline")
        self.assertEqual(base, "https://www.facebook.com/SomePageName")

    def test_numeric_path_becomes_profile_php(self):
        nav, _, base = normalize_facebook_profile_input("https://www.facebook.com/61589216603998")
        self.assertEqual(nav, "https://www.facebook.com/profile.php?id=61589216603998")
        self.assertEqual(base, "https://www.facebook.com/61589216603998")

    def test_canonical_storage_numeric(self):
        self.assertEqual(
            canonical_facebook_username_for_storage("https://www.facebook.com/profile.php?id=61589216603998"),
            "61589216603998",
        )
        self.assertEqual(canonical_facebook_username_for_storage("61589216603998"), "61589216603998")

    def test_canonical_storage_vanity(self):
        self.assertEqual(canonical_facebook_username_for_storage("SomePageName"), "SomePageName")
        self.assertEqual(
            canonical_facebook_username_for_storage("https://www.facebook.com/SomePageName"),
            "SomePageName",
        )
