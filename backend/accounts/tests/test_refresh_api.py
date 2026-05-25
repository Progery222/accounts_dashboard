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

    @patch("accounts.views._scrape")
    def test_failed_refresh_preserves_updated_at(self, mock_scrape):
        old = timezone.now() - timedelta(days=3)
        Account.objects.filter(pk=self.account.pk).update(updated_at=old)
        self.account.refresh_from_db()
        mock_scrape.return_value = {
            "follower_count": 0,
            "like_count": 0,
            "view_count": 0,
            "post_count": 0,
            "_posts": [],
        }

        response = self.client.post(f"/api/accounts/{self.account.id}/refresh/")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        self.account.refresh_from_db()
        self.assertEqual(self.account.follower_count, 100)
        self.assertEqual(self.account.updated_at, old)

    @patch("accounts.views._scrape")
    def test_scrape_error_preserves_updated_at(self, mock_scrape):
        old = timezone.now() - timedelta(days=2)
        Account.objects.filter(pk=self.account.pk).update(updated_at=old)
        self.account.refresh_from_db()
        mock_scrape.side_effect = ValueError("timeout")

        response = self.client.post(f"/api/accounts/{self.account.id}/refresh/")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        self.account.refresh_from_db()
        self.assertEqual(self.account.updated_at, old)

    @patch("accounts.views._refresh_with_retry")
    def test_refresh_maps_value_error_to_400(self, mock_refresh):
        mock_refresh.side_effect = ValueError("Профиль не найден")

        response = self.client.post(f"/api/accounts/{self.account.id}/refresh/")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("detail", response.data)

    @patch("accounts.views._refresh_with_retry")
    def test_refresh_maps_unexpected_error_to_500(self, mock_refresh):
        mock_refresh.side_effect = RuntimeError("timeout")

        response = self.client.post(f"/api/accounts/{self.account.id}/refresh/")
        self.assertEqual(response.status_code, status.HTTP_500_INTERNAL_SERVER_ERROR)
        self.assertIn("detail", response.data)

    @patch("accounts.refresh_all_warm.RefreshAllWarmTracker")
    @patch("accounts.views._refresh_with_retry")
    def test_refresh_all_continues_on_partial_failures(self, mock_refresh, mock_warm_tracker):
        mock_warm_tracker.return_value.after_network_refresh = lambda *a, **k: None
        second = Account.objects.create(username="broken", platform=Platform.TIKTOK)

        def _side_effect(account, scraped=None):
            if account.id == second.id:
                raise ValueError("Профиль недоступен")
            account.follower_count += 1
            account.save(update_fields=["follower_count"])
            return account

        mock_refresh.side_effect = _side_effect

        start = self.client.post("/api/accounts/refresh_all/")
        self.assertEqual(start.status_code, status.HTTP_200_OK)
        self.assertTrue(start.data.get("started"))

        import time
        for _ in range(200):
            st = self.client.get("/api/accounts/refresh-all-status/")
            self.assertEqual(st.status_code, status.HTTP_200_OK)
            if not st.data.get("is_running"):
                break
            time.sleep(0.05)
        else:
            self.fail("refresh_all did not finish in time")

        self.assertEqual(st.data.get("success_accounts"), 1)
        self.assertEqual(st.data.get("failed_accounts"), 1)
        self.assertIsNotNone(st.data.get("last_error"))
        self.assertIn("Последняя", st.data.get("last_error") or "")
        cs = st.data.get("completion_summary")
        self.assertIsInstance(cs, dict)
        self.assertEqual(cs.get("failed_count"), 1)
        self.assertTrue(st.data.get("has_csv_report"))
        rr = st.data.get("report_run")
        self.assertIsInstance(rr, dict)
        self.assertEqual(rr.get("row_count"), 2)
        rpt = self.client.get("/api/accounts/refresh-all-report/")
        self.assertEqual(rpt.status_code, 200)
        body = rpt.content.decode("utf-8-sig")
        self.assertIn("ID аккаунта", body)
        self.assertIn("ИТОГ прогона", body)
        self.assertIn("Всего секунд", body)

    @patch("accounts.views._scrape")
    def test_threads_refresh_clears_unavailable_when_followers_parse_as_zero(self, mock_scrape):
        """Регрессия: follower_count у Threads часто 0 при живом профиле — не блокировать сохранение."""
        acc = Account.objects.create(
            username="yllazenlab",
            platform=Platform.THREADS,
            follower_count=120,
            like_count=0,
            view_count=200,
            post_count=11,
            profile_unavailable=True,
        )
        mock_scrape.return_value = {
            "display_name": "yllazenlab",
            "follower_count": 0,
            "avatar_url": "",
            "bio": "",
            "like_count": 0,
            "post_count": 11,
            "_posts": [
                {
                    "external_id": "p1",
                    "description": "",
                    "view_count": 204,
                    "like_count": 0,
                    "comment_count": 0,
                    "share_count": 0,
                },
            ],
        }
        response = self.client.post(f"/api/accounts/{acc.id}/refresh/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        acc.refresh_from_db()
        self.assertFalse(acc.profile_unavailable)
        self.assertEqual(acc.follower_count, 0)
        self.assertEqual(acc.view_count, 204)

    @patch("accounts.views._scrape")
    def test_threads_refresh_clears_unavailable_when_likes_drop_to_zero(self, mock_scrape):
        """Регрессия: агрегат like_count у Threads может стать 0 — не откатывать сохранение."""
        acc = Account.objects.create(
            username="realyllazen",
            platform=Platform.THREADS,
            follower_count=0,
            like_count=40,
            view_count=114,
            post_count=3,
            profile_unavailable=True,
        )
        mock_scrape.return_value = {
            "display_name": "realyllazen",
            "follower_count": 0,
            "avatar_url": "",
            "bio": "",
            "like_count": 0,
            "post_count": 3,
            "_posts": [
                {
                    "external_id": "a",
                    "description": "",
                    "view_count": 80,
                    "like_count": 0,
                    "comment_count": 0,
                    "share_count": 0,
                },
            ],
        }
        response = self.client.post(f"/api/accounts/{acc.id}/refresh/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        acc.refresh_from_db()
        self.assertFalse(acc.profile_unavailable)
        self.assertEqual(acc.like_count, 0)
        self.assertGreaterEqual(acc.view_count, 114)

    @patch("accounts.views._scrape")
    def test_x_refresh_empty_posts_clears_unavailable(self, mock_scrape):
        """Регрессия: пустая лента X и follower_count=0 не должны залипать в profile_unavailable."""
        acc = Account.objects.create(
            username="bob_spanch5411",
            platform=Platform.X,
            follower_count=1200,
            like_count=0,
            view_count=0,
            post_count=0,
            profile_unavailable=True,
        )
        mock_scrape.return_value = {
            "display_name": "Evelyn Brooks",
            "follower_count": 0,
            "avatar_url": "",
            "bio": "",
            "like_count": 0,
            "post_count": 0,
            "_posts": [],
        }
        response = self.client.post(f"/api/accounts/{acc.id}/refresh/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        acc.refresh_from_db()
        self.assertFalse(acc.profile_unavailable)
        self.assertEqual(acc.follower_count, 0)
        self.assertEqual(acc.post_count, 0)

    @patch("accounts.views._scrape")
    def test_x_refresh_empty_posts_does_not_mark_existing_posts_missing(self, mock_scrape):
        acc = Account.objects.create(
            username="zoepark_sec",
            platform=Platform.X,
            follower_count=100,
            post_count=1,
        )
        post = Post.objects.create(
            account=acc,
            external_id="old_tweet",
            description="legacy",
            view_count=50,
        )
        mock_scrape.return_value = {
            "display_name": "Zoe Park",
            "follower_count": 100,
            "avatar_url": "",
            "bio": "",
            "like_count": 0,
            "post_count": 1,
            "_posts": [],
        }
        response = self.client.post(f"/api/accounts/{acc.id}/refresh/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        post.refresh_from_db()
        self.assertIsNone(post.missing_from_scrape_at)
