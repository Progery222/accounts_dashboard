from datetime import timedelta
from unittest.mock import patch

from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import Account, Platform, Post
from accounts.views import _apply_post_aggregates_to_account, _sync_posts


class PostMissingFromScrapeTests(APITestCase):
    def setUp(self):
        self.account = Account.objects.create(
            username="demo_user",
            platform=Platform.TIKTOK,
            follower_count=100,
            post_count=2,
        )
        self.old_post = Post.objects.create(
            account=self.account,
            external_id="gone",
            description="old",
            view_count=50,
        )
        self.keep_post = Post.objects.create(
            account=self.account,
            external_id="stay",
            description="stay",
            view_count=80,
        )

    def test_aggregates_exclude_missing_posts_without_lowering_stats(self):
        self.account.view_count = 130
        self.account.like_count = 10
        self.account.post_count = 2
        self.account.save(update_fields=["view_count", "like_count", "post_count"])
        _sync_posts(
            self.account,
            [
                {
                    "external_id": "stay",
                    "description": "stay",
                    "view_count": 90,
                    "like_count": 2,
                    "comment_count": 0,
                    "share_count": 0,
                },
            ],
        )
        stats_before = {"view_count": 130, "like_count": 10, "post_count": 2}
        _apply_post_aggregates_to_account(self.account, stats_before)
        self.account.refresh_from_db()
        self.assertGreaterEqual(self.account.view_count, 130)
        self.assertGreaterEqual(self.account.like_count, 10)
        self.assertGreaterEqual(self.account.post_count, 2)

    def test_sync_posts_marks_missing_instead_of_deleting(self):
        _sync_posts(
            self.account,
            [
                {
                    "external_id": "stay",
                    "description": "stay updated",
                    "view_count": 90,
                    "like_count": 1,
                    "comment_count": 0,
                    "share_count": 0,
                },
            ],
        )
        self.assertEqual(Post.objects.filter(account=self.account).count(), 2)
        self.old_post.refresh_from_db()
        self.keep_post.refresh_from_db()
        self.assertIsNotNone(self.old_post.missing_from_scrape_at)
        self.assertIsNone(self.keep_post.missing_from_scrape_at)
        self.assertEqual(self.keep_post.view_count, 90)

    def test_sync_posts_clears_missing_when_post_returns(self):
        self.old_post.missing_from_scrape_at = timezone.now()
        self.old_post.save(update_fields=["missing_from_scrape_at"])
        _sync_posts(
            self.account,
            [
                {
                    "external_id": "gone",
                    "description": "back",
                    "view_count": 55,
                    "like_count": 0,
                    "comment_count": 0,
                    "share_count": 0,
                },
                {
                    "external_id": "stay",
                    "description": "stay",
                    "view_count": 80,
                    "like_count": 0,
                    "comment_count": 0,
                    "share_count": 0,
                },
            ],
        )
        self.old_post.refresh_from_db()
        self.assertIsNone(self.old_post.missing_from_scrape_at)

    def test_delete_post_endpoint(self):
        response = self.client.delete(
            f"/api/accounts/{self.account.id}/posts/{self.old_post.id}/",
        )
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(Post.objects.filter(pk=self.old_post.pk).exists())

    def test_analytics_top_posts_scrape_filter_missing(self):
        self.old_post.missing_from_scrape_at = timezone.now()
        self.old_post.save(update_fields=["missing_from_scrape_at"])
        response = self.client.get(
            "/api/accounts/analytics/top-posts/",
            {"scrape_filter": "missing", "min_views": 0, "page_size": 50},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(data.get("scrape_filter"), "missing")
        ids = [item["id"] for item in data.get("items", [])]
        self.assertIn(self.old_post.id, ids)
        self.assertNotIn(self.keep_post.id, ids)
        missing_item = next(i for i in data["items"] if i["id"] == self.old_post.id)
        self.assertTrue(missing_item.get("scrape_not_found"))

    @patch("accounts.views._scrape")
    def test_refresh_clears_missing_when_post_returns(self, mock_scrape):
        self.old_post.missing_from_scrape_at = timezone.now()
        self.old_post.save(update_fields=["missing_from_scrape_at"])
        mock_scrape.return_value = {
            "follower_count": 100,
            "post_count": 2,
            "_posts": [
                {
                    "external_id": "gone",
                    "description": "back",
                    "view_count": 55,
                    "like_count": 0,
                    "comment_count": 0,
                    "share_count": 0,
                },
                {
                    "external_id": "stay",
                    "description": "stay",
                    "view_count": 90,
                    "like_count": 0,
                    "comment_count": 0,
                    "share_count": 0,
                },
            ],
        }
        response = self.client.post(f"/api/accounts/{self.account.id}/refresh/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.old_post.refresh_from_db()
        self.assertIsNone(self.old_post.missing_from_scrape_at)

    @patch("accounts.views._scrape")
    def test_refresh_keeps_missing_post(self, mock_scrape):
        mock_scrape.return_value = {
            "follower_count": 100,
            "post_count": 1,
            "_posts": [
                {
                    "external_id": "stay",
                    "description": "stay",
                    "view_count": 100,
                    "like_count": 0,
                    "comment_count": 0,
                    "share_count": 0,
                },
            ],
        }
        response = self.client.post(f"/api/accounts/{self.account.id}/refresh/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(Post.objects.filter(account=self.account, external_id="gone").exists())
        gone = Post.objects.get(account=self.account, external_id="gone")
        self.assertIsNotNone(gone.missing_from_scrape_at)
