from rest_framework import status
from rest_framework.test import APITestCase


class DeltaPeriodQueryParamTests(APITestCase):
    def test_accounts_list_accepts_delta_period_days(self):
        r = self.client.get("/api/accounts/", {"delta_period_days": "7"})
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertIsInstance(r.data, list)

    def test_summary_accepts_delta_period_days(self):
        r = self.client.get("/api/accounts/summary/", {"delta_period_days": "30"})
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertIn("follower_count", r.data)
