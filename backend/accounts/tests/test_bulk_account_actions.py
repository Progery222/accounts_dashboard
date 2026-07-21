from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import Account, Owner, Platform, Profile


class BulkAccountActionsTests(APITestCase):
    def setUp(self):
        self.p1 = Profile.objects.create(name="P1")
        self.p2 = Profile.objects.create(name="P2")
        self.o1 = Owner.objects.create(name="O1")
        self.a1 = Account.objects.create(
            username="u1",
            platform=Platform.TIKTOK,
            profile=self.p1,
            is_archived=False,
        )
        self.a2 = Account.objects.create(
            username="u2",
            platform=Platform.INSTAGRAM,
            profile=self.p1,
            is_archived=False,
        )

    def test_bulk_update_archive_and_owner(self):
        r = self.client.post(
            "/api/accounts/bulk-update/",
            {
                "ids": [self.a1.id, self.a2.id],
                "is_archived": True,
                "owner_id": self.o1.id,
                "profile_id": self.p2.id,
            },
            format="json",
        )
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertEqual(r.data["updated"], 2)
        self.a1.refresh_from_db()
        self.a2.refresh_from_db()
        self.assertTrue(self.a1.is_archived)
        self.assertTrue(self.a2.is_archived)
        self.assertEqual(self.a1.owner_id, self.o1.id)
        self.assertEqual(self.a1.profile_id, self.p2.id)

    def test_bulk_update_clear_owner(self):
        self.a1.owner = self.o1
        self.a1.save(update_fields=["owner"])
        r = self.client.post(
            "/api/accounts/bulk-update/",
            {"ids": [self.a1.id], "owner_id": None},
            format="json",
        )
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.a1.refresh_from_db()
        self.assertIsNone(self.a1.owner_id)

    def test_bulk_delete(self):
        r = self.client.post(
            "/api/accounts/bulk-delete/",
            {"ids": [self.a1.id, self.a2.id, 999999]},
            format="json",
        )
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertEqual(r.data["deleted"], 2)
        self.assertFalse(Account.objects.filter(id__in=[self.a1.id, self.a2.id]).exists())

    def test_bulk_update_requires_ids(self):
        r = self.client.post("/api/accounts/bulk-update/", {"is_archived": True}, format="json")
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)
