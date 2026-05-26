from datetime import timedelta
from io import BytesIO

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import (
    Account,
    AccountSnapshot,
    AutoRefreshPoint,
    Platform,
    Post,
    PostSnapshot,
    Profile,
)
from accounts.snapshot_io import build_snapshot_csv, import_snapshot_csv


class SnapshotIoRoundTripTests(TestCase):
    def test_export_import_preserves_extended_fields(self):
        prof = Profile.objects.create(
            name="Team A",
            color="#ff0000",
            description="Desc",
            avatar_url="https://example.com/p.png",
            is_hidden=True,
        )
        posted = timezone.now() - timedelta(days=3)
        acc = Account.objects.create(
            username="snap_user",
            platform=Platform.TIKTOK,
            profile=prof,
            display_name="Snap",
            follower_count=1000,
            like_count=200,
            view_count=5000,
            post_count=4,
            link_click_count=42,
            profile_unavailable=True,
        )
        snap_date = timezone.now().date() - timedelta(days=1)
        AccountSnapshot.objects.create(
            account=acc,
            date=snap_date,
            follower_count=900,
            like_count=180,
            view_count=4000,
            post_count=3,
            link_click_count=30,
        )
        post = Post.objects.create(
            account=acc,
            external_id="vid1",
            description="hello",
            view_count=100,
            posted_at=posted,
        )
        PostSnapshot.objects.create(
            post=post,
            date=snap_date,
            view_count=80,
            like_count=5,
            comment_count=1,
        )

        csv_bytes = build_snapshot_csv()
        summary = import_snapshot_csv(BytesIO(csv_bytes))

        self.assertEqual(summary["errors"], [])
        acc2 = Account.objects.get(username="snap_user", platform=Platform.TIKTOK)
        self.assertEqual(acc2.link_click_count, 42)
        self.assertTrue(acc2.profile_unavailable)
        prof2 = Profile.objects.get(name="Team A")
        self.assertEqual(prof2.description, "Desc")
        self.assertEqual(prof2.avatar_url, "https://example.com/p.png")
        self.assertTrue(prof2.is_hidden)
        hist = AccountSnapshot.objects.get(account=acc2, date=snap_date)
        self.assertEqual(hist.link_click_count, 30)
        post2 = Post.objects.get(account=acc2, external_id="vid1")
        self.assertIsNotNone(post2.posted_at)
        self.assertEqual(post2.posted_at.date(), posted.date())

    def test_legacy_csv_without_new_columns_keeps_link_clicks_on_update(self):
        acc = Account.objects.create(
            username="legacy",
            platform=Platform.X,
            link_click_count=99,
            profile_unavailable=True,
        )
        legacy = (
            "# ACCOUNTS\n"
            "username,platform,follower_count,like_count,view_count,post_count\n"
            "legacy,x,10,20,30,1\n"
        ).encode("utf-8")
        summary = import_snapshot_csv(BytesIO(legacy))
        self.assertEqual(summary["errors"], [])
        acc.refresh_from_db()
        self.assertEqual(acc.follower_count, 10)
        self.assertEqual(acc.link_click_count, 99)
        self.assertTrue(acc.profile_unavailable)

    def test_import_post_snapshots_without_posts_section(self):
        acc = Account.objects.create(username="ig_user", platform=Platform.INSTAGRAM)
        snap_date = timezone.now().date() - timedelta(days=2)
        csv = (
            "# ACCOUNTS\n"
            "username,platform,follower_count,like_count,view_count,post_count\n"
            "ig_user,instagram,1,2,3,4\n"
            "\n# POST_SNAPSHOTS\n"
            "account_platform,account_username,post_external_id,date,view_count,like_count,comment_count\n"
            f"instagram,ig_user,ShortCode1,{snap_date.isoformat()},10,2,1\n"
        ).encode("utf-8")
        summary = import_snapshot_csv(BytesIO(csv))
        self.assertEqual(summary["errors"], [])
        self.assertEqual(summary["post_snapshots_upserted"], 1)
        self.assertEqual(summary["posts_created"], 1)
        post = Post.objects.get(account=acc, external_id="ShortCode1")
        snap = PostSnapshot.objects.get(post=post, date=snap_date)
        self.assertEqual(snap.view_count, 10)

    def test_export_import_auto_refresh_points_for_live_charts(self):
        t0 = timezone.now() - timedelta(hours=6)
        t1 = timezone.now() - timedelta(hours=3)
        AutoRefreshPoint.objects.create(
            measured_at=t0,
            local_date=timezone.localtime(t0).date(),
            source="scheduler",
            slot_label="06:00",
            view_count_total=1000,
            view_delta_from_prev_point=100,
            view_delta_from_day_start=100,
            platform_deltas={"tiktok": 80, "instagram": 20},
        )
        AutoRefreshPoint.objects.create(
            measured_at=t1,
            local_date=timezone.localtime(t1).date(),
            source="scheduler",
            slot_label="12:00",
            view_count_total=2500,
            view_delta_from_prev_point=1500,
            view_delta_from_day_start=2500,
            platform_deltas={"tiktok": 1200, "instagram": 300},
        )
        csv_bytes = build_snapshot_csv()
        self.assertIn(b"# AUTO_REFRESH_POINTS", csv_bytes)
        AutoRefreshPoint.objects.all().delete()
        summary = import_snapshot_csv(BytesIO(csv_bytes))
        self.assertEqual(summary["errors"], [])
        self.assertEqual(summary["auto_refresh_points_imported"], 2)
        self.assertFalse(summary.get("auto_refresh_chart_times_remapped"))
        pts = list(AutoRefreshPoint.objects.order_by("measured_at"))
        self.assertEqual(len(pts), 2)
        self.assertEqual(pts[-1].view_count_total, 2500)
        self.assertEqual(pts[-1].platform_deltas.get("tiktok"), 1200)

    def test_import_spreads_collapsed_chart_times(self):
        t0 = timezone.now() - timedelta(minutes=5)
        for i, total in enumerate([100, 200, 350]):
            AutoRefreshPoint.objects.create(
                measured_at=t0 + timedelta(milliseconds=i),
                local_date=timezone.localtime(t0).date(),
                view_count_total=total,
                view_delta_from_prev_point=total - (100 if i == 0 else [100, 200][i - 1]),
                view_delta_from_day_start=total - 100,
                platform_deltas={"tiktok": 50},
            )
        csv_bytes = build_snapshot_csv()
        AutoRefreshPoint.objects.all().delete()
        summary = import_snapshot_csv(BytesIO(csv_bytes))
        self.assertTrue(summary["auto_refresh_chart_times_remapped"])
        pts = list(AutoRefreshPoint.objects.order_by("measured_at"))
        span = (pts[-1].measured_at - pts[0].measured_at).total_seconds()
        self.assertGreaterEqual(span, 3600)

    def test_import_remaps_stale_chart_times_into_last_24h(self):
        t_old = timezone.now() - timedelta(days=3)
        t_newer = timezone.now() - timedelta(days=2)
        AutoRefreshPoint.objects.create(
            measured_at=t_old,
            local_date=timezone.localtime(t_old).date(),
            view_count_total=100,
            view_delta_from_prev_point=0,
            view_delta_from_day_start=100,
            platform_deltas={},
        )
        AutoRefreshPoint.objects.create(
            measured_at=t_newer,
            local_date=timezone.localtime(t_newer).date(),
            view_count_total=500,
            view_delta_from_prev_point=400,
            view_delta_from_day_start=500,
            platform_deltas={"tiktok": 400},
        )
        csv_bytes = build_snapshot_csv()
        AutoRefreshPoint.objects.all().delete()
        summary = import_snapshot_csv(BytesIO(csv_bytes))
        self.assertEqual(summary["errors"], [])
        self.assertTrue(summary["auto_refresh_chart_times_remapped"])
        pts = list(AutoRefreshPoint.objects.order_by("measured_at"))
        window_start = timezone.now() - timedelta(hours=24)
        self.assertGreaterEqual(pts[0].measured_at, window_start - timedelta(seconds=5))

    def test_import_rebuilds_flat_chart_totals(self):
        t0 = timezone.now() - timedelta(hours=3)
        for i in range(4):
            AutoRefreshPoint.objects.create(
                measured_at=t0 + timedelta(minutes=i),
                local_date=timezone.localtime(t0).date(),
                view_count_total=10_000,
                view_delta_from_prev_point=0,
                view_delta_from_day_start=400 if i == 3 else 0,
                platform_deltas={},
            )
        csv_bytes = build_snapshot_csv()
        AutoRefreshPoint.objects.all().delete()
        summary = import_snapshot_csv(BytesIO(csv_bytes))
        self.assertTrue(summary.get("auto_refresh_chart_totals_rebuilt"))
        pts = list(AutoRefreshPoint.objects.order_by("measured_at"))
        spread = pts[-1].view_count_total - pts[0].view_count_total
        self.assertGreaterEqual(spread, 200)

    def test_export_posts_section_covers_post_snapshots(self):
        acc = Account.objects.create(username="phil", platform=Platform.INSTAGRAM)
        post = Post.objects.create(account=acc, external_id="DXwHZKjqHk7", view_count=5)
        d = timezone.now().date() - timedelta(days=1)
        PostSnapshot.objects.create(post=post, date=d, view_count=3, like_count=1, comment_count=0)
        text = build_snapshot_csv().decode("utf-8-sig")
        self.assertIn("# POSTS", text)
        self.assertIn("DXwHZKjqHk7", text)
        self.assertIn("# POST_SNAPSHOTS", text)


class SnapshotIoApiTests(APITestCase):
    def test_export_and_import_endpoints(self):
        Account.objects.create(username="api_user", platform=Platform.INSTAGRAM, follower_count=7)
        export = self.client.get("/api/accounts/export-snapshot/")
        self.assertEqual(export.status_code, status.HTTP_200_OK)
        self.assertIn("text/csv", export["Content-Type"])

        upload = SimpleUploadedFile("snapshot.csv", export.content, content_type="text/csv")
        imp = self.client.post("/api/accounts/import-snapshot/", {"file": upload}, format="multipart")
        self.assertEqual(imp.status_code, status.HTTP_200_OK)
        self.assertIn("accounts_updated", imp.json())
