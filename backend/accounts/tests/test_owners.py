from datetime import timedelta

from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIRequestFactory, APITestCase

from accounts.models import Account, Owner, Platform, Profile


class OwnerApiTests(APITestCase):
    def test_owner_crud_and_account_count(self):
        owner = Owner.objects.create(name="Петя", color="#22c55e")
        Account.objects.create(username="u1", platform=Platform.TIKTOK, owner=owner)
        Account.objects.create(username="u2", platform=Platform.INSTAGRAM, owner=owner)

        list_r = self.client.get("/api/accounts/owners/")
        self.assertEqual(list_r.status_code, status.HTTP_200_OK)
        row = next(x for x in list_r.data if x["id"] == owner.id)
        self.assertEqual(row["account_count"], 2)

        patch_r = self.client.patch(
            f"/api/accounts/owners/{owner.id}/",
            {"name": "Петя 2", "color": "#ef4444"},
            format="json",
        )
        self.assertEqual(patch_r.status_code, status.HTTP_200_OK)
        owner.refresh_from_db()
        self.assertEqual(owner.name, "Петя 2")

        del_r = self.client.delete(f"/api/accounts/owners/{owner.id}/")
        self.assertEqual(del_r.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(Owner.objects.filter(pk=owner.id).exists())
        self.assertIsNone(Account.objects.get(username="u1", platform=Platform.TIKTOK).owner_id)


class AccountOwnerUpsertTests(APITestCase):
    def test_import_updates_owner_and_profile(self):
        prof = Profile.objects.create(name="Музыка", color="#a855f7")
        old_owner = Owner.objects.create(name="Старый", color="#111111")
        new_owner = Owner.objects.create(name="Петя", color="#22c55e")
        Account.objects.create(
            username="chan",
            platform=Platform.INSTAGRAM,
            profile=prof,
            owner=old_owner,
            view_count=100,
        )

        factory = APIRequestFactory()
        request = factory.post(
            "/api/accounts/",
            {
                "username": "chan",
                "platform": "instagram",
                "profile_id": prof.id,
                "owner_id": new_owner.id,
            },
            format="json",
        )
        view = __import__(
            "accounts.views", fromlist=["AccountViewSet"]
        ).AccountViewSet.as_view({"post": "create"})
        response = view(request)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data.get("import_action"), "assignment_updated")
        self.assertIn("owner", response.data.get("changed_fields", []))
        acc = Account.objects.get(username="chan", platform=Platform.INSTAGRAM)
        self.assertEqual(acc.owner_id, new_owner.id)
        self.assertEqual(acc.view_count, 100)

    def test_import_unchanged_when_same_assignment(self):
        owner = Owner.objects.create(name="Петя", color="#22c55e")
        Account.objects.create(username="x", platform=Platform.TIKTOK, owner=owner)

        factory = APIRequestFactory()
        request = factory.post(
            "/api/accounts/",
            {"username": "x", "platform": "tiktok", "owner_id": owner.id},
            format="json",
        )
        view = __import__(
            "accounts.views", fromlist=["AccountViewSet"]
        ).AccountViewSet.as_view({"post": "create"})
        response = view(request)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data.get("import_action"), "unchanged")

    def test_patch_owner_preserves_updated_at(self):
        prof = Profile.objects.create(name="P", color="#6366f1")
        owner = Owner.objects.create(name="Новый", color="#22c55e")
        marker = timezone.now() - timedelta(days=3)
        acc = Account.objects.create(
            username="keep_ts",
            platform=Platform.TIKTOK,
            profile=prof,
            view_count=42,
        )
        Account.objects.filter(pk=acc.pk).update(updated_at=marker)
        acc.refresh_from_db()

        patch_r = self.client.patch(
            f"/api/accounts/{acc.id}/",
            {"owner_id": owner.id},
            format="json",
        )
        self.assertEqual(patch_r.status_code, status.HTTP_200_OK)
        acc.refresh_from_db()
        self.assertEqual(acc.owner_id, owner.id)
        self.assertEqual(acc.view_count, 42)
        self.assertEqual(acc.updated_at, marker)

    def test_import_assignment_preserves_updated_at(self):
        prof = Profile.objects.create(name="P", color="#6366f1")
        new_owner = Owner.objects.create(name="Петя", color="#22c55e")
        marker = timezone.now() - timedelta(days=5)
        Account.objects.create(username="imp", platform=Platform.TIKTOK, profile=prof, view_count=10)
        Account.objects.filter(username="imp", platform=Platform.TIKTOK).update(updated_at=marker)

        factory = APIRequestFactory()
        request = factory.post(
            "/api/accounts/",
            {"username": "imp", "platform": "tiktok", "owner_id": new_owner.id},
            format="json",
        )
        view = __import__(
            "accounts.views", fromlist=["AccountViewSet"]
        ).AccountViewSet.as_view({"post": "create"})
        response = view(request)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        acc = Account.objects.get(username="imp", platform=Platform.TIKTOK)
        self.assertEqual(acc.owner_id, new_owner.id)
        self.assertEqual(acc.updated_at, marker)
