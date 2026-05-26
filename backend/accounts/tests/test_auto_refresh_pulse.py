from datetime import timedelta

from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from accounts.auto_refresh_pulse import (
    create_auto_refresh_point_from_report_rows,
    enter_refresh_pulse_batch,
    exit_refresh_pulse_batch,
    record_account_refresh_platform_delta,
)
from accounts.models import Account, AccountSnapshot, AutoRefreshPoint, Platform


class AutoRefreshPulseTests(APITestCase):
    def test_record_creates_point_with_platform_delta(self):
        acc = Account.objects.create(
            platform=Platform.TIKTOK,
            username="pulse_tt",
            view_count=1000,
        )
        record_account_refresh_platform_delta(Platform.TIKTOK, 990, 1009, source="refresh")
        pt = AutoRefreshPoint.objects.order_by("-measured_at").first()
        self.assertIsNotNone(pt)
        self.assertEqual(pt.platform_deltas.get("tiktok"), 19)

    def test_batch_mode_skips_incremental(self):
        AutoRefreshPoint.objects.all().delete()
        enter_refresh_pulse_batch()
        try:
            record_account_refresh_platform_delta(Platform.TIKTOK, 0, 50, source="refresh")
        finally:
            exit_refresh_pulse_batch()
        self.assertEqual(AutoRefreshPoint.objects.count(), 0)

    def test_create_from_report_rows(self):
        AutoRefreshPoint.objects.all().delete()
        create_auto_refresh_point_from_report_rows(
            [
                {"platform": "tiktok", "view_before": 100, "view_after": 109},
                {"platform": "facebook", "view_before": 200, "view_after": 216},
            ],
            source="scheduler",
        )
        pt = AutoRefreshPoint.objects.get()
        self.assertEqual(pt.platform_deltas.get("tiktok"), 9)
        self.assertEqual(pt.platform_deltas.get("facebook"), 16)
        self.assertEqual(pt.source, "scheduler")

    def test_merge_incremental_within_window(self):
        AutoRefreshPoint.objects.all().delete()
        now = timezone.now()
        AutoRefreshPoint.objects.create(
            local_date=timezone.localdate(),
            source="refresh",
            slot_label="10:00",
            measured_at=now - timedelta(minutes=10),
            view_count_total=5000,
            view_delta_from_prev_point=0,
            view_delta_from_day_start=0,
            platform_deltas={"tiktok": 5},
        )
        record_account_refresh_platform_delta(Platform.TIKTOK, 100, 104, source="refresh")
        self.assertEqual(AutoRefreshPoint.objects.count(), 1)
        pt = AutoRefreshPoint.objects.get()
        self.assertEqual(pt.platform_deltas.get("tiktok"), 9)


class SummaryPlatformViewDeltaTests(APITestCase):
    def test_by_platform_includes_view_delta(self):
        today = timezone.localdate()
        yesterday = today - timedelta(days=1)
        acc = Account.objects.create(
            platform=Platform.TIKTOK,
            username="summary_tt",
            view_count=500,
        )
        AccountSnapshot.objects.create(
            account=acc,
            date=yesterday,
            follower_count=0,
            like_count=0,
            view_count=491,
            post_count=0,
        )
        r = self.client.get("/api/accounts/summary/", {"delta_period_days": "1"})
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        row = next(x for x in r.data["by_platform"] if x["platform"] == Platform.TIKTOK)
        self.assertEqual(row["view_delta"], 9)
