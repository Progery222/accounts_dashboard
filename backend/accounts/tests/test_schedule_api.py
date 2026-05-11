from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import RefreshScheduleConfig


class RefreshScheduleApiTests(APITestCase):
    def test_enabled_false_string_is_parsed_correctly(self):
        RefreshScheduleConfig.objects.update_or_create(
            pk=1,
            defaults={
                "enabled": True,
                "mode": "interval",
                "interval_hours": 6,
                "times": [],
            },
        )

        response = self.client.post("/api/accounts/schedule/", {"enabled": "false"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(response.data["enabled"])

    def test_auto_refresh_csv_report_toggle(self):
        RefreshScheduleConfig.objects.update_or_create(
            pk=1,
            defaults={
                "enabled": False,
                "mode": "interval",
                "interval_hours": 6,
                "times": [],
                "auto_refresh_csv_report": False,
            },
        )

        r = self.client.get("/api/accounts/schedule/")
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertIn("auto_refresh_csv_report", r.data)
        self.assertFalse(r.data["auto_refresh_csv_report"])

        r2 = self.client.post(
            "/api/accounts/schedule/",
            {"auto_refresh_csv_report": True},
            format="json",
        )
        self.assertEqual(r2.status_code, status.HTTP_200_OK)
        self.assertTrue(r2.data["auto_refresh_csv_report"])

    def test_auto_refresh_status_includes_run_detail(self):
        r = self.client.get("/api/accounts/auto-refresh-status/")
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertIn("run_detail", r.data)
        self.assertIsInstance(r.data["run_detail"], dict)
        self.assertIn("skip_recent_hours_config", r.data)
