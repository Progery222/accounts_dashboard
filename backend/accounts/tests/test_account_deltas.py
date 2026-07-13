from datetime import timedelta

from django.utils import timezone
from django.test import TestCase

from accounts.constants import NEW_ACCOUNT_UPDATED_AT
from accounts.models import Account, AccountGroup, AccountSnapshot, Country, Platform, Profile
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

    def test_import_create_sets_marker_updated_at(self):
        from rest_framework.test import APIRequestFactory

        factory = APIRequestFactory()
        request = factory.post(
            "/api/accounts/",
            {"username": "brand_new", "platform": "tiktok"},
            format="json",
        )
        view = __import__(
            "accounts.views", fromlist=["AccountViewSet"]
        ).AccountViewSet.as_view({"post": "create"})
        response = view(request)
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data.get("import_action"), "created")
        acc = Account.objects.get(username="brand_new", platform=Platform.TIKTOK)
        self.assertEqual(acc.updated_at, NEW_ACCOUNT_UPDATED_AT)

    def test_import_create_unchanged_when_same_profile(self):
        from rest_framework.test import APIRequestFactory

        profile = Profile.objects.create(name="P1", color="#6366f1")
        Account.objects.create(
            username="move_user",
            platform=Platform.TIKTOK,
            profile=profile,
            view_count=999,
        )
        factory = APIRequestFactory()
        request = factory.post(
            "/api/accounts/",
            {"username": "move_user", "platform": "tiktok", "profile_id": profile.id},
            format="json",
        )
        view = __import__(
            "accounts.views", fromlist=["AccountViewSet"]
        ).AccountViewSet.as_view({"post": "create"})
        response = view(request)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data.get("import_action"), "unchanged")
        self.assertEqual(
            Account.objects.get(username="move_user", platform=Platform.TIKTOK).view_count,
            999,
        )

    def test_import_create_updates_profile_only(self):
        from rest_framework.test import APIRequestFactory

        old = Profile.objects.create(name="Old", color="#111111")
        new = Profile.objects.create(name="New", color="#222222")
        Account.objects.create(
            username="move_user2",
            platform=Platform.TIKTOK,
            profile=old,
            view_count=500,
        )
        factory = APIRequestFactory()
        request = factory.post(
            "/api/accounts/",
            {"username": "move_user2", "platform": "tiktok", "profile_id": new.id},
            format="json",
        )
        view = __import__(
            "accounts.views", fromlist=["AccountViewSet"]
        ).AccountViewSet.as_view({"post": "create"})
        response = view(request)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data.get("import_action"), "assignment_updated")
        self.assertIn("profile", response.data.get("changed_fields", []))
        acc = Account.objects.get(username="move_user2", platform=Platform.TIKTOK)
        self.assertEqual(acc.profile_id, new.id)
        self.assertEqual(acc.view_count, 500)

    def test_import_create_updates_group_only(self):
        from rest_framework.test import APIRequestFactory

        profile = Profile.objects.create(name="P", color="#6366f1")
        old_group = AccountGroup.objects.create(name="G1", color="#111111")
        new_group = AccountGroup.objects.create(name="G2", color="#222222")
        Account.objects.create(
            username="grp_user",
            platform=Platform.TIKTOK,
            profile=profile,
            group=old_group,
            view_count=800,
        )
        factory = APIRequestFactory()
        request = factory.post(
            "/api/accounts/",
            {
                "username": "grp_user",
                "platform": "tiktok",
                "profile_id": profile.id,
                "group_id": new_group.id,
            },
            format="json",
        )
        view = __import__(
            "accounts.views", fromlist=["AccountViewSet"]
        ).AccountViewSet.as_view({"post": "create"})
        response = view(request)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data.get("import_action"), "assignment_updated")
        self.assertEqual(response.data.get("changed_fields"), ["group"])
        acc = Account.objects.get(username="grp_user", platform=Platform.TIKTOK)
        self.assertEqual(acc.group_id, new_group.id)
        self.assertEqual(acc.profile_id, profile.id)
        self.assertEqual(acc.view_count, 800)

    def test_import_create_unchanged_when_same_group_and_profile(self):
        from rest_framework.test import APIRequestFactory

        profile = Profile.objects.create(name="P", color="#6366f1")
        group = AccountGroup.objects.create(name="G", color="#333333")
        Account.objects.create(
            username="same_grp",
            platform=Platform.TIKTOK,
            profile=profile,
            group=group,
            view_count=111,
        )
        factory = APIRequestFactory()
        request = factory.post(
            "/api/accounts/",
            {
                "username": "same_grp",
                "platform": "tiktok",
                "profile_id": profile.id,
                "group_id": group.id,
            },
            format="json",
        )
        view = __import__(
            "accounts.views", fromlist=["AccountViewSet"]
        ).AccountViewSet.as_view({"post": "create"})
        response = view(request)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data.get("import_action"), "unchanged")

    def test_import_create_updates_country_preserves_updated_at(self):
        from rest_framework.test import APIRequestFactory

        profile = Profile.objects.create(name="P", color="#6366f1")
        old_country = Country.objects.create(name="RU", color="#111111")
        new_country = Country.objects.create(name="US", color="#222222")
        marker = timezone.now() - timedelta(days=4)
        Account.objects.create(
            username="cty_user",
            platform=Platform.TIKTOK,
            profile=profile,
            country=old_country,
            view_count=50,
        )
        Account.objects.filter(username="cty_user", platform=Platform.TIKTOK).update(
            updated_at=marker,
        )
        factory = APIRequestFactory()
        request = factory.post(
            "/api/accounts/",
            {
                "username": "cty_user",
                "platform": "tiktok",
                "profile_id": profile.id,
                "country_id": new_country.id,
            },
            format="json",
        )
        view = __import__(
            "accounts.views", fromlist=["AccountViewSet"]
        ).AccountViewSet.as_view({"post": "create"})
        response = view(request)
        self.assertEqual(response.status_code, 200)
        acc = Account.objects.get(username="cty_user", platform=Platform.TIKTOK)
        self.assertEqual(acc.country_id, new_country.id)
        self.assertEqual(acc.view_count, 50)
        self.assertEqual(acc.updated_at, marker)

    def test_patch_group_preserves_updated_at(self):
        from rest_framework.test import APIRequestFactory

        profile = Profile.objects.create(name="P", color="#6366f1")
        group = AccountGroup.objects.create(name="G", color="#444444")
        marker = timezone.now() - timedelta(days=2)
        acc = Account.objects.create(
            username="patch_grp",
            platform=Platform.TIKTOK,
            profile=profile,
            view_count=77,
        )
        Account.objects.filter(pk=acc.pk).update(updated_at=marker)
        factory = APIRequestFactory()
        view = __import__(
            "accounts.views", fromlist=["AccountViewSet"]
        ).AccountViewSet.as_view({"patch": "partial_update"})
        request = factory.patch(
            f"/api/accounts/{acc.id}/",
            {"group_id": group.id},
            format="json",
        )
        response = view(request, pk=acc.id)
        self.assertEqual(response.status_code, 200)
        acc.refresh_from_db()
        self.assertEqual(acc.group_id, group.id)
        self.assertEqual(acc.view_count, 77)
        self.assertEqual(acc.updated_at, marker)

    def test_patch_profile_unavailable_manual_toggle(self):
        from rest_framework.test import APIRequestFactory

        acc = Account.objects.create(
            username="manual_unavail",
            platform=Platform.TIKTOK,
            profile_unavailable=False,
            view_count=100,
        )
        before = acc.updated_at
        factory = APIRequestFactory()
        view = __import__(
            "accounts.views", fromlist=["AccountViewSet"]
        ).AccountViewSet.as_view({"patch": "partial_update"})
        request = factory.patch(
            f"/api/accounts/{acc.id}/",
            {"profile_unavailable": True},
            format="json",
        )
        response = view(request, pk=acc.id)
        self.assertEqual(response.status_code, 200)
        acc.refresh_from_db()
        self.assertTrue(acc.profile_unavailable)
        self.assertEqual(acc.updated_at, before)

        request = factory.patch(
            f"/api/accounts/{acc.id}/",
            {"profile_unavailable": False},
            format="json",
        )
        response = view(request, pk=acc.id)
        self.assertEqual(response.status_code, 200)
        acc.refresh_from_db()
        self.assertFalse(acc.profile_unavailable)
