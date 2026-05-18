from datetime import timedelta

from django.utils import timezone
from django.test import TestCase

from accounts.models import Account, AccountSnapshot, Platform
from accounts.serializers import AccountSerializer


class AccountDeltaSerializerTests(TestCase):
    def test_serializer_returns_deltas_from_previous_snapshot(self):
        account = Account.objects.create(
            username="delta_user",
            platform=Platform.TIKTOK,
            follower_count=120,
            like_count=40,
            view_count=300,
            post_count=12,
        )
        AccountSnapshot.objects.create(
            account=account,
            date=timezone.now().date() - timedelta(days=1),
            follower_count=100,
            like_count=30,
            view_count=250,
            post_count=10,
        )

        payload = AccountSerializer(account).data
        self.assertEqual(payload["follower_delta"], 20)
        self.assertEqual(payload["like_delta"], 10)
        self.assertEqual(payload["view_delta"], 50)
        self.assertEqual(payload["post_delta"], 2)

    def test_serializer_treats_missing_baseline_snapshot_as_zero(self):
        account = Account.objects.create(
            username="new_user",
            platform=Platform.TIKTOK,
            follower_count=10,
            like_count=5,
            view_count=15,
            post_count=1,
        )

        payload = AccountSerializer(account).data
        self.assertEqual(payload["follower_delta"], 10)
        self.assertEqual(payload["like_delta"], 5)
        self.assertEqual(payload["view_delta"], 15)
        self.assertEqual(payload["post_delta"], 1)

    def test_serializer_baseline_respects_seven_day_context(self):
        today = timezone.localdate()
        account = Account.objects.create(
            username="delta_week",
            platform=Platform.TIKTOK,
            follower_count=200,
            like_count=0,
            view_count=0,
            post_count=0,
        )
        AccountSnapshot.objects.create(
            account=account,
            date=today - timedelta(days=8),
            follower_count=50,
            like_count=0,
            view_count=0,
            post_count=0,
        )
        AccountSnapshot.objects.create(
            account=account,
            date=today - timedelta(days=1),
            follower_count=100,
            like_count=0,
            view_count=0,
            post_count=0,
        )
        ctx = {"account_delta_period_days": 7, "hidden_platforms": set()}
        payload = AccountSerializer(account, context=ctx).data
        self.assertEqual(payload["follower_delta"], 150)

    def test_facebook_like_delta_hidden_when_like_count_zero(self):
        today = timezone.localdate()
        account = Account.objects.create(
            username="61588868450712",
            platform=Platform.FACEBOOK,
            follower_count=1,
            like_count=0,
            view_count=1000,
            post_count=5,
        )
        AccountSnapshot.objects.create(
            account=account,
            date=today - timedelta(days=1),
            follower_count=1,
            like_count=9,
            view_count=900,
            post_count=5,
        )
        payload = AccountSerializer(account).data
        self.assertIsNone(payload["like_delta"])

    def test_instagram_view_delta_never_negative_without_annotation(self):
        today = timezone.localdate()
        account = Account.objects.create(
            username="ig_view_floor",
            platform=Platform.INSTAGRAM,
            follower_count=1,
            like_count=0,
            view_count=100,
            post_count=5,
        )
        AccountSnapshot.objects.create(
            account=account,
            date=today - timedelta(days=1),
            follower_count=1,
            like_count=0,
            view_count=200,
            post_count=5,
        )
        payload = AccountSerializer(account).data
        self.assertEqual(payload["view_delta"], 0)
        self.assertEqual(payload["follower_delta"], 0)
