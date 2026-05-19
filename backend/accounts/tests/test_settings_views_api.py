from unittest.mock import patch

from rest_framework import status
from rest_framework.test import APITestCase


class SettingsViewsApiTests(APITestCase):
    @patch("accounts.settings_views._tiktok_status", return_value={"has_session": False})
    @patch("accounts.settings_views._instagram_status", return_value={"has_session": False})
    @patch("accounts.settings_views._telegram_status", return_value={"has_session": False})
    @patch("accounts.settings_views._x_status", return_value={"has_session": False})
    @patch("accounts.settings_views._threads_status", return_value={"has_session": False})
    @patch("accounts.settings_views._facebook_status", return_value={"has_session": False})
    @patch("accounts.settings_views._rumble_status", return_value={"has_session": False})
    def test_auth_status_contains_all_platform_keys(
        self,
        _rumble,
        _facebook,
        _threads,
        _x,
        _telegram,
        _instagram,
        _tiktok,
    ):
        response = self.client.get("/api/settings/status/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        keys = set(response.data.keys())
        for platform in ("tiktok", "instagram", "telegram", "x", "threads", "facebook", "rumble", "reddit"):
            self.assertIn(platform, keys)
        self.assertNotIn("shard_count", keys)
        self.assertNotIn("shards", keys)

    @patch("accounts.settings_views._logout_platform")
    def test_logout_supported_platforms_return_ok(self, mock_logout):
        for platform in ("tiktok", "instagram", "telegram", "x", "threads", "facebook", "rumble"):
            response = self.client.post(f"/api/settings/{platform}/logout/")
            self.assertEqual(response.status_code, status.HTTP_200_OK, msg=platform)
            self.assertTrue(response.data.get("ok"), msg=platform)
        self.assertEqual(mock_logout.call_count, 7)

    def test_logout_unknown_platform_returns_404(self):
        response = self.client.post("/api/settings/unknown/logout/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
