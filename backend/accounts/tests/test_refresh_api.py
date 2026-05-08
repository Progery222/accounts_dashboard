from datetime import timedelta
from unittest.mock import patch

from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import Account, AccountSnapshot, Platform, Post


class RefreshApiTests(APITestCase):
    def setUp(self):
        self.account = Account.objects.create(
            username="demo_user",
            platform=Platform.TIKTOK,
            follower_count=100,
            like_count=50,
            view_count=10,
            post_count=1,
        )

    @patch("accounts.views._scrape")
    def test_refresh_updates_account_and_keeps_snapshot_baseline(self, mock_scrape):
        yesterday = timezone.now().date() - timedelta(days=1)
        AccountSnapshot.objects.create(
            account=self.account,
            date=yesterday,
            follower_count=100,
            like_count=50,
            view_count=10,
            post_count=1,
        )
        mock_scrape.return_value = {
            "display_name": "Demo",
            "follower_count": 125,
            "like_count": 70,
            "post_count": 2,
            "_posts": [
                {
                    "external_id": "p1",
                    "description": "first",
                    "view_count": 200,
                    "like_count": 80,
                    "comment_count": 3,
                    "share_count": 1,
                },
                {
                    "external_id": "p2",
                    "description": "second",
                    "view_count": 30,
                    "like_count": 20,
                    "comment_count": 2,
                    "share_count": 0,
                },
            ],
        }

        response = self.client.post(f"/api/accounts/{self.account.id}/refresh/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.account.refresh_from_db()
        self.assertEqual(self.account.follower_count, 125)
        # TikTok like_count приходит с платформы, не из агрегата постов
        self.assertEqual(self.account.like_count, 70)
        # view_count агрегируется из постов
        self.assertEqual(self.account.view_count, 230)
        self.assertEqual(self.account.post_count, 2)
        self.assertEqual(Post.objects.filter(account=self.account).count(), 2)

        today = timezone.now().date()
        today_snap = AccountSnapshot.objects.get(account=self.account, date=today)
        self.assertEqual(today_snap.follower_count, 125)
        self.assertEqual(today_snap.view_count, 230)

        # Исторический snapshot не должен перетираться текущими значениями.
        baseline = AccountSnapshot.objects.get(account=self.account, date=yesterday)
        self.assertEqual(baseline.follower_count, 100)
        self.assertEqual(baseline.view_count, 10)

    @patch("accounts.views._refresh_with_retry")
    def test_refresh_maps_value_error_to_400(self, mock_refresh):
        mock_refresh.side_effect = ValueError("Профиль не найден")

        response = self.client.post(f"/api/accounts/{self.account.id}/refresh/")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("detail", response.data)

    @patch("accounts.views._refresh_with_retry")
    def test_refresh_maps_unexpected_error_to_502(self, mock_refresh):
        mock_refresh.side_effect = RuntimeError("timeout")

        response = self.client.post(f"/api/accounts/{self.account.id}/refresh/")
        self.assertEqual(response.status_code, status.HTTP_502_BAD_GATEWAY)
        self.assertIn("detail", response.data)

    @patch("accounts.views._refresh_with_retry")
    def test_refresh_all_continues_on_partial_failures(self, mock_refresh):
        second = Account.objects.create(username="broken", platform=Platform.TIKTOK)

        def _side_effect(account, scraped=None):
            if account.id == second.id:
                raise ValueError("Профиль недоступен")
            account.follower_count += 1
            account.save(update_fields=["follower_count"])
            return account

        mock_refresh.side_effect = _side_effect

        response = self.client.post("/api/accounts/refresh_all/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["refreshed"], 1)
        self.assertEqual(response.data["failed"], 1)
        self.assertEqual(len(response.data["report"]), 2)
