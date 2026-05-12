from django.test import SimpleTestCase, TestCase
from rest_framework import status
from rest_framework.test import APITestCase

from accounts.audience import sync_audience_from_payload
from accounts.models import Account, AccountAudienceMembership, AudienceMember, AudienceMemberPost, Platform


class TikTokFollowerXhrParseTests(SimpleTestCase):
    def test_parse_userlist_only_not_deep_nested(self):
        from platforms.tiktok.audience_scrape import _parse_follower_relation_xhr_rows

        payload = {
            "userList": [
                {"uniqueId": "fan_a", "secUid": "1"},
                {"uniqueId": "fan_b", "secUid": "2"},
            ],
            "item": {
                "user": {
                    "uniqueId": "other",
                    "embed": {"userList": [{"uniqueId": "nested_wrong", "secUid": "99"}]},
                },
            },
        }
        rows = _parse_follower_relation_xhr_rows(payload, "owner")
        self.assertEqual({r["username"] for r in rows}, {"fan_a", "fan_b"})


class AudienceSyncTests(TestCase):
    def test_sync_creates_members_posts_and_prunes_removed(self):
        acc = Account.objects.create(
            username="owner",
            platform=Platform.TIKTOK,
            follower_count=1,
            like_count=0,
            view_count=0,
            post_count=0,
        )
        payload = {
            "followers": [
                {
                    "username": "fan_one",
                    "external_id": "sec1",
                    "display_name": "Fan One",
                    "avatar_url": "",
                    "bio": "hi",
                    "is_private": False,
                    "follower_count": 10,
                    "following_count": 2,
                    "like_count": 0,
                    "posts": [
                        {
                            "external_id": "v1",
                            "description": "d",
                            "thumbnail_url": "",
                            "post_url": "https://www.tiktok.com/@fan_one/video/v1",
                            "view_count": 100,
                            "like_count": 5,
                            "comment_count": 0,
                            "share_count": 0,
                            "posted_at": None,
                        },
                    ],
                },
                {
                    "username": "fan_two",
                    "external_id": "",
                    "display_name": "",
                    "avatar_url": "",
                    "bio": "",
                    "is_private": True,
                    "follower_count": 0,
                    "following_count": 0,
                    "like_count": 0,
                    "posts": [],
                },
            ],
        }
        r1 = sync_audience_from_payload(acc, payload)
        self.assertEqual(r1["followers_saved"], 2)
        self.assertEqual(AccountAudienceMembership.objects.filter(account=acc).count(), 2)
        self.assertEqual(AudienceMemberPost.objects.count(), 1)

        acc.refresh_from_db()
        self.assertIsNotNone(acc.audience_last_synced_at)

        # Второй съём: fan_two пропал — связь удаляется
        sync_audience_from_payload(
            acc,
            {"followers": [{"username": "fan_one", "external_id": "sec1", "posts": []}]},
        )
        self.assertEqual(AccountAudienceMembership.objects.filter(account=acc).count(), 1)
        self.assertEqual(
            AccountAudienceMembership.objects.filter(
                account=acc,
                member__username="fan_two",
            ).count(),
            0,
        )
        self.assertTrue(
            AudienceMember.objects.filter(platform=Platform.TIKTOK, username="fan_one").exists(),
        )

    def test_reuse_existing_keeps_member_fields_and_membership(self):
        acc = Account.objects.create(
            username="owner_ig",
            platform=Platform.INSTAGRAM,
            follower_count=0,
            like_count=0,
            view_count=0,
            post_count=0,
        )
        m = AudienceMember.objects.create(
            platform=Platform.INSTAGRAM,
            username="keep_me",
            display_name="Старое имя",
            bio="старое био",
        )
        AccountAudienceMembership.objects.create(account=acc, member=m)
        sync_audience_from_payload(
            acc,
            {"followers": [{"username": "keep_me", "_reuse_existing": True, "posts": []}]},
        )
        m.refresh_from_db()
        self.assertEqual(m.display_name, "Старое имя")
        self.assertEqual(m.bio, "старое био")
        self.assertTrue(AccountAudienceMembership.objects.filter(account=acc, member=m).exists())


class AudienceMemberDeleteApiTests(APITestCase):
    def setUp(self):
        self.acc = Account.objects.create(
            username="owner_del",
            platform=Platform.TIKTOK,
            follower_count=0,
            like_count=0,
            view_count=0,
            post_count=0,
        )
        self.member = AudienceMember.objects.create(
            platform=Platform.TIKTOK,
            username="fan_del",
            external_id="",
            display_name="Fan",
        )
        AccountAudienceMembership.objects.create(account=self.acc, member=self.member)

    def test_delete_removes_membership_and_orphan_member(self):
        url = f"/api/accounts/{self.acc.id}/audience/{self.member.id}/"
        r = self.client.delete(url)
        self.assertEqual(r.status_code, status.HTTP_204_NO_CONTENT)
        self.assertEqual(AccountAudienceMembership.objects.filter(account=self.acc).count(), 0)
        self.assertFalse(AudienceMember.objects.filter(pk=self.member.pk).exists())

    def test_delete_only_this_account_keeps_shared_member(self):
        acc2 = Account.objects.create(
            username="owner2",
            platform=Platform.TIKTOK,
            follower_count=0,
            like_count=0,
            view_count=0,
            post_count=0,
        )
        AccountAudienceMembership.objects.create(account=acc2, member=self.member)
        r = self.client.delete(f"/api/accounts/{self.acc.id}/audience/{self.member.id}/")
        self.assertEqual(r.status_code, status.HTTP_204_NO_CONTENT)
        self.assertEqual(AccountAudienceMembership.objects.filter(member=self.member).count(), 1)
        self.assertTrue(AudienceMember.objects.filter(pk=self.member.pk).exists())

    def test_delete_wrong_member_404(self):
        r = self.client.delete(f"/api/accounts/{self.acc.id}/audience/99999999/")
        self.assertEqual(r.status_code, status.HTTP_404_NOT_FOUND)
