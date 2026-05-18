"""Режимы audience_mode: list / enrich / full."""
from django.test import TestCase

from accounts.audience import normalize_audience_mode, sync_audience_from_payload
from accounts.models import Account, AccountAudienceMembership, AudienceMember, Platform


class AudienceModesTest(TestCase):
    def test_normalize_audience_mode(self):
        self.assertEqual(normalize_audience_mode("list"), "list")
        self.assertEqual(normalize_audience_mode("FULL"), "full")
        with self.assertRaises(ValueError):
            normalize_audience_mode("nope")

    def test_sync_list_preserves_bio_on_existing_member(self):
        acc = Account.objects.create(username="owner1", platform=Platform.TIKTOK)
        member = AudienceMember.objects.create(
            platform=Platform.TIKTOK,
            username="fan1",
            bio="Старое био",
            follower_count=100,
        )
        AccountAudienceMembership.objects.create(account=acc, member=member)
        payload = {
            "owner_username": "owner1",
            "audience_mode": "list",
            "followers": [
                {"username": "fan1", "display_name": "Fan"},
            ],
        }
        sync_audience_from_payload(acc, payload, audience_mode="list")
        member.refresh_from_db()
        self.assertEqual(member.bio, "Старое био")
        self.assertEqual(member.follower_count, 100)

    def test_sync_enrich_does_not_prune_memberships(self):
        acc = Account.objects.create(username="owner2", platform=Platform.X)
        m1 = AudienceMember.objects.create(platform=Platform.X, username="a", bio="")
        m2 = AudienceMember.objects.create(platform=Platform.X, username="b", bio="")
        AccountAudienceMembership.objects.create(account=acc, member=m1)
        AccountAudienceMembership.objects.create(account=acc, member=m2)
        payload = {
            "owner_username": "owner2",
            "audience_mode": "enrich",
            "followers": [
                {"username": "a", "bio": "новое", "follower_count": 5},
            ],
        }
        sync_audience_from_payload(acc, payload, audience_mode="enrich")
        self.assertEqual(
            AccountAudienceMembership.objects.filter(account=acc).count(),
            2,
        )
        m1.refresh_from_db()
        self.assertEqual(m1.bio, "новое")

    def test_sync_enrich_returns_member_summaries(self):
        acc = Account.objects.create(username="owner3", platform=Platform.INSTAGRAM)
        payload = {
            "owner_username": "owner3",
            "audience_mode": "enrich",
            "followers": [
                {
                    "username": "fan1",
                    "display_name": "Fan One",
                    "bio": "Привет",
                    "follower_count": 42,
                    "following_count": 3,
                    "_enrich_ok": True,
                },
                {
                    "username": "fan2",
                    "display_name": "",
                    "bio": "",
                    "follower_count": 0,
                    "_enrich_ok": False,
                    "_enrich_note": "Слабый разбор",
                },
            ],
        }
        out = sync_audience_from_payload(acc, payload, audience_mode="enrich")
        self.assertEqual(out["followers_saved"], 2)
        self.assertEqual(len(out["enriched_members"]), 2)
        self.assertEqual(out["enriched_ok_count"], 1)
        self.assertEqual(out["enriched_weak_count"], 1)
        self.assertEqual(out["enriched_members"][0]["username"], "fan1")
        self.assertTrue(out["enriched_members"][0]["enrich_ok"])
        self.assertFalse(out["enriched_members"][1]["enrich_ok"])
