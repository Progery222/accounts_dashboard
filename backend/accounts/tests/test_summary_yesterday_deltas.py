"""GET /api/accounts/summary/ — вчерашние дневные дельты по снимкам для TV-графиков."""

import datetime

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import Account, AccountSnapshot, Platform


class SummaryYesterdayDeltasTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_yesterday_deltas_sum_snap_minus_prev_day(self):
        today = timezone.localdate()
        y = today - datetime.timedelta(days=1)
        b = today - datetime.timedelta(days=2)

        a1 = Account.objects.create(
            username="u1",
            platform=Platform.TIKTOK,
            follower_count=200,
            like_count=50,
            view_count=1000,
            post_count=20,
        )
        a2 = Account.objects.create(
            username="u2",
            platform=Platform.TIKTOK,
            follower_count=100,
            like_count=30,
            view_count=500,
            post_count=10,
        )

        AccountSnapshot.objects.create(
            account=a1, date=b, follower_count=100, like_count=40, view_count=800, post_count=15
        )
        AccountSnapshot.objects.create(
            account=a1, date=y, follower_count=110, like_count=42, view_count=900, post_count=17
        )
        AccountSnapshot.objects.create(
            account=a2, date=b, follower_count=50, like_count=20, view_count=400, post_count=8
        )
        AccountSnapshot.objects.create(
            account=a2, date=y, follower_count=55, like_count=21, view_count=450, post_count=9
        )

        r = self.client.get("/api/accounts/summary/")
        self.assertEqual(r.status_code, 200)
        p = r.json()
        self.assertEqual(p["yesterday_follower_delta"], (110 - 100) + (55 - 50))
        self.assertEqual(p["yesterday_like_delta"], (42 - 40) + (21 - 20))
        self.assertEqual(p["yesterday_view_delta"], (900 - 800) + (450 - 400))
        self.assertEqual(p["yesterday_post_delta"], (17 - 15) + (9 - 8))

    def test_yesterday_deltas_null_without_both_days(self):
        today = timezone.localdate()
        y = today - datetime.timedelta(days=1)

        a = Account.objects.create(
            username="solo",
            platform=Platform.TIKTOK,
            follower_count=10,
            like_count=5,
            view_count=100,
            post_count=2,
        )
        AccountSnapshot.objects.create(
            account=a, date=y, follower_count=8, like_count=4, view_count=90, post_count=1
        )

        r = self.client.get("/api/accounts/summary/")
        self.assertEqual(r.status_code, 200)
        p = r.json()
        self.assertIsNone(p["yesterday_follower_delta"])
        self.assertIsNone(p["yesterday_like_delta"])
        self.assertIsNone(p["yesterday_view_delta"])
        self.assertIsNone(p["yesterday_post_delta"])

    def test_yesterday_deltas_fallback_last_two_snapshots(self):
        """Нет пары за календарный вчера/позавчера — берём последние два снимка до сегодня (дельта между датами)."""
        today = timezone.localdate()
        d_old = today - datetime.timedelta(days=14)
        d_new = today - datetime.timedelta(days=13)

        a = Account.objects.create(
            username="hist",
            platform=Platform.TIKTOK,
            follower_count=99,
            like_count=10,
            view_count=200,
            post_count=3,
        )
        AccountSnapshot.objects.create(
            account=a,
            date=d_old,
            follower_count=100,
            like_count=5,
            view_count=100,
            post_count=1,
        )
        AccountSnapshot.objects.create(
            account=a,
            date=d_new,
            follower_count=130,
            like_count=8,
            view_count=160,
            post_count=2,
        )

        r = self.client.get("/api/accounts/summary/")
        self.assertEqual(r.status_code, 200)
        p = r.json()
        self.assertEqual(p["yesterday_follower_delta"], 30)
        self.assertEqual(p["yesterday_like_delta"], 3)
        self.assertEqual(p["yesterday_view_delta"], 60)
        self.assertEqual(p["yesterday_post_delta"], 1)
