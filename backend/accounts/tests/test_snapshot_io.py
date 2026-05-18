from datetime import timedelta
from io import BytesIO

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import Account, AccountSnapshot, Platform, Post, Profile
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
