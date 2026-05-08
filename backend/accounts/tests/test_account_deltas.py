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

    def test_serializer_returns_none_deltas_without_previous_snapshot(self):
        account = Account.objects.create(
            username="new_user",
            platform=Platform.TIKTOK,
            follower_count=10,
            like_count=5,
            view_count=15,
            post_count=1,
        )

        payload = AccountSerializer(account).data
        self.assertIsNone(payload["follower_delta"])
        self.assertIsNone(payload["like_delta"])
        self.assertIsNone(payload["view_delta"])
        self.assertIsNone(payload["post_delta"])
