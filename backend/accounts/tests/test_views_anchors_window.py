"""GET /api/accounts/views-anchors/ — окно роста 10:00–20:00 МСК."""
from datetime import datetime, timedelta
from unittest import mock
from zoneinfo import ZoneInfo

from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from accounts.models import Account, AccountSnapshot, Platform
from accounts.views import VIEWS_ANCHOR_HOUR, VIEWS_GROWTH_END_HOUR


MSK = ZoneInfo("Europe/Moscow")


@override_settings(TIME_ZONE="Europe/Moscow")
class ViewsAnchorsWindowTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.acc = Account.objects.create(
            username="vc_user",
            platform=Platform.TIKTOK,
            view_count=100_000,
            follower_count=1000,
            like_count=500,
            post_count=10,
        )

    def _snap(self, day, views, followers=1000):
        AccountSnapshot.objects.create(
            account=self.acc,
            date=day,
            view_count=views,
            follower_count=followers,
            like_count=500,
            post_count=10,
        )

    def _get_at(self, when: datetime):
        with mock.patch("django.utils.timezone.localtime", return_value=when):
            return self.client.get("/api/accounts/views-anchors/")

    def test_growth_window_is_10_to_20_same_day(self):
        """В 15:00 окно — сегодня 10:00→20:00, next — завтра 10:00."""
        when = datetime(2026, 9, 10, 15, 0, 0, tzinfo=MSK)
        day = when.date()
        self._snap(day - timedelta(days=1), 50_000, followers=800)
        self._snap(day, 100_000, followers=1000)

        r = self._get_at(when)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["anchor_hour"], VIEWS_ANCHOR_HOUR)
        self.assertEqual(r.data["growth_end_hour"], VIEWS_GROWTH_END_HOUR)

        start = datetime.fromisoformat(r.data["window_start"])
        end = datetime.fromisoformat(r.data["window_end"])
        nxt = datetime.fromisoformat(r.data["next_window_start"])
        self.assertEqual(start.hour, 10)
        self.assertEqual(end.hour, 20)
        self.assertEqual(start.date(), day)
        self.assertEqual(end.date(), day)
        self.assertEqual((end - start).total_seconds(), 10 * 3600)
        self.assertEqual(nxt, start + timedelta(days=1))
        self.assertEqual(nxt.hour, 10)

        views = r.data["metrics"]["views"]
        self.assertEqual(views["prev"], 50_000)
        self.assertEqual(views["now"], 100_000)
        self.assertEqual(views["growth"], 50_000)

    def test_before_10_uses_yesterdays_window_frozen(self):
        """В 09:00 ещё вчерашнее окно 10→20; next — сегодня 10:00."""
        when = datetime(2026, 9, 10, 9, 0, 0, tzinfo=MSK)
        y = (when - timedelta(days=1)).date()
        self._snap(y - timedelta(days=1), 40_000)
        self._snap(y, 50_000)

        r = self._get_at(when)
        self.assertEqual(r.status_code, 200)
        start = datetime.fromisoformat(r.data["window_start"])
        end = datetime.fromisoformat(r.data["window_end"])
        nxt = datetime.fromisoformat(r.data["next_window_start"])
        self.assertEqual(start.date(), y)
        self.assertEqual(start.hour, 10)
        self.assertEqual(end.hour, 20)
        self.assertEqual(nxt.date(), when.date())
        self.assertEqual(nxt.hour, 10)
        self.assertEqual(r.data["metrics"]["views"]["growth"], 10_000)

    def test_after_20_keeps_same_day_window(self):
        """В 22:00 окно всё ещё сегодня 10→20 (фронт заморожен на финише)."""
        when = datetime(2026, 9, 10, 22, 0, 0, tzinfo=MSK)
        day = when.date()
        self._snap(day - timedelta(days=1), 50_000)
        self._snap(day, 100_000)

        r = self._get_at(when)
        start = datetime.fromisoformat(r.data["window_start"])
        end = datetime.fromisoformat(r.data["window_end"])
        self.assertEqual(start.date(), day)
        self.assertEqual(end.hour, 20)
        self.assertLess(end, when)
        self.assertEqual(r.data["metrics"]["views"]["growth"], 50_000)
