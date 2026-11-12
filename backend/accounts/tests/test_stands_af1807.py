"""AF-1807: стенды — аналитика по стенду, ряд для поп-апа карточек, «Убрать», «Перенести», сущности в постах."""
import datetime

from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import (
    Account, AccountGroup, AccountSnapshot, AutoRefreshPoint, Country, Domain, Owner, Platform, Post, Profile, Topic,
)
from accounts.views import _sync_posts


class StandsBase(APITestCase):
    def setUp(self):
        self.dom, _ = Domain.objects.get_or_create(slug="stands", defaults={"name": "Стенды"})
        self.other_dom, _ = Domain.objects.get_or_create(slug="ferma", defaults={"name": "Ферма"})
        self.s1 = Topic.objects.create(name="Стенд 1", slug="stand-1", board="stands", sort_order=10)
        self.s4 = Topic.objects.create(name="Стенд 4", slug="stand-4", board="stands", sort_order=40)
        self.a1 = Account.objects.create(username="alpha", platform=Platform.TIKTOK, domain=self.dom,
                                         follower_count=100, view_count=1000, like_count=10, post_count=5)
        self.a2 = Account.objects.create(username="beta", platform=Platform.TIKTOK, domain=self.dom,
                                         follower_count=200, view_count=2000, like_count=20, post_count=6)
        self.a3 = Account.objects.create(username="gamma", platform=Platform.INSTAGRAM, domain=self.dom)
        self.far = Account.objects.create(username="faraway", platform=Platform.TIKTOK, domain=self.other_dom)
        self.s1.accounts.add(self.a1, self.a2, self.a3)
        self.s4.accounts.add(self.far)

    def post(self, url, body):
        return self.client.post(url, body, format="json", HTTP_X_DOMAIN="stands")


class AnalyticsByStandTests(StandsBase):
    def setUp(self):
        super().setUp()
        Post.objects.create(account=self.a1, external_id="1", description="on stand 1", view_count=500)
        Post.objects.create(account=self.far, external_id="2", description="on stand 4", view_count=900)
        Post.objects.create(account=Account.objects.create(username="nobody", platform=Platform.TIKTOK),
                            external_id="3", description="not on stands", view_count=10_000)

    def top(self, topic=""):
        url = "/api/accounts/analytics/top-posts/?period=all&sort_by=views&min_views=0" + (f"&topic={topic}" if topic else "")
        return self.client.get(url, HTTP_X_DOMAIN="stands")

    def test_all_stands_are_scoped_to_board(self):
        r = self.top()
        self.assertEqual(r.status_code, 200)
        self.assertEqual({p["description"] for p in r.data["items"]}, {"on stand 1", "on stand 4"})

    def test_single_stand(self):
        r = self.top(self.s4.id)
        self.assertEqual([p["description"] for p in r.data["items"]], ["on stand 4"])
        r = self.client.get(f"/api/accounts/analytics/insights/?period=all&min_views=0&topic={self.s1.id}",
                            HTTP_X_DOMAIN="stands")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(sum(x["post_count"] for x in r.data["platform_comparison"]), 1)


class SeriesTests(StandsBase):
    def test_daily_series_fills_gaps_and_ends_with_current(self):
        today = timezone.localdate()
        AccountSnapshot.objects.create(account=self.a1, date=today - datetime.timedelta(days=3), follower_count=70)
        AccountSnapshot.objects.create(account=self.a1, date=today - datetime.timedelta(days=1), follower_count=90)
        AccountSnapshot.objects.create(account=self.a2, date=today - datetime.timedelta(days=2), follower_count=150)
        r = self.post("/api/accounts/analytics/series/",
                      {"account_ids": [self.a1.id, self.a2.id], "metric": "followers", "period": "7d"})
        self.assertEqual(r.status_code, 200, r.data)
        pts = r.data["points"]
        self.assertEqual(len(pts), 8)              # 7 дней + «сейчас»
        self.assertEqual(pts[-1]["v"], 300)       # текущие 100 + 200
        # день −3: a1=70, a2 ещё без снимка → первый известный (150)
        self.assertEqual(pts[4]["v"], 220)
        self.assertEqual(pts[6]["v"], 240)        # день −1: 90 + 150
        self.assertEqual(r.data["delta"], 300 - pts[0]["v"])

    def test_day_views_use_refresh_points(self):
        now = timezone.now()
        p = AutoRefreshPoint.objects.create(local_date=timezone.localdate(), account_totals={str(self.a1.id): 900})
        AutoRefreshPoint.objects.filter(pk=p.pk).update(measured_at=now - datetime.timedelta(hours=2))
        r = self.post("/api/accounts/analytics/series/", {"account_ids": [self.a1.id], "metric": "views", "period": "1d"})
        self.assertEqual(r.data["granularity"], "point")
        self.assertEqual([x["v"] for x in r.data["points"]][-2:], [900, 1000])

    def test_validation(self):
        r = self.post("/api/accounts/analytics/series/", {"account_ids": [1], "metric": "nope", "period": "7d"})
        self.assertEqual(r.status_code, 400)


class RemoveFromStandTests(StandsBase):
    def test_remove_from_current_stand_by_link_and_pick(self):
        self.s4.accounts.add(self.a2)  # beta стоит на двух стендах
        r = self.post("/api/accounts/topics/remove-accounts/", {
            "topic_id": self.s1.id,
            "items": [{"username": "alpha", "platform": "tiktok"}, {"username": "BETA", "platform": "tiktok"}],
            "account_ids": [self.a3.id],
        })
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["removed"], 3)
        self.assertEqual(list(self.s1.accounts.all()), [])
        self.assertTrue(self.s4.accounts.filter(pk=self.a2.pk).exists())   # со Стенда 4 не трогали
        self.a1.refresh_from_db(); self.a2.refresh_from_db()
        self.assertTrue(self.a1.is_archived)      # больше нигде не стоит → архив
        self.assertFalse(self.a2.is_archived)     # стоит на Стенде 4

    def test_not_on_this_stand(self):
        r = self.post("/api/accounts/topics/remove-accounts/", {"topic_id": self.s1.id, "account_ids": [self.far.id]})
        self.assertEqual(r.data["removed"], 0)
        self.assertEqual(r.data["not_here"], ["faraway"])
        self.assertTrue(self.s4.accounts.filter(pk=self.far.pk).exists())


class MoveToStandTests(StandsBase):
    def test_move_with_labels(self):
        prof, own = Profile.objects.create(name="P"), Owner.objects.create(name="O")
        grp, cty = AccountGroup.objects.create(name="G"), Country.objects.create(name="C")
        self.a1.is_archived = True
        self.a1.save(update_fields=["is_archived"])
        r = self.post(f"/api/accounts/topics/{self.s4.id}/move-accounts/", {
            "items": [{"username": "@alpha", "platform": "tiktok"}, {"username": "ghost", "platform": "tiktok"}],
            "profile_id": prof.id, "owner_id": own.id, "group_id": grp.id, "country_id": cty.id,
        })
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["moved"], 1)
        self.assertEqual(r.data["not_found"], ["ghost"])
        self.assertEqual(r.data["from"], {"Стенд 1": 1})
        self.assertFalse(self.s1.accounts.filter(pk=self.a1.pk).exists())
        self.assertTrue(self.s4.accounts.filter(pk=self.a1.pk).exists())
        self.a1.refresh_from_db()
        self.assertEqual((self.a1.profile_id, self.a1.owner_id, self.a1.group_id, self.a1.country_id),
                         (prof.id, own.id, grp.id, cty.id))
        self.assertFalse(self.a1.is_archived)

    def test_move_keeps_labels_when_not_given(self):
        prof = Profile.objects.create(name="Keep")
        self.a2.profile = prof
        self.a2.save(update_fields=["profile"])
        r = self.post(f"/api/accounts/topics/{self.s4.id}/move-accounts/", {"items": [{"username": "beta", "platform": ""}]})
        self.assertEqual(r.data["moved"], 1)
        self.a2.refresh_from_db()
        self.assertEqual(self.a2.profile_id, prof.id)


class PostEntitiesTests(StandsBase):
    def test_sync_unescapes_and_no_fake_hashtag(self):
        _sync_posts(self.a1, [{"external_id": "77", "description": "last night&#39;s LIVE &amp; more #real"}])
        p = Post.objects.get(account=self.a1, external_id="77")
        self.assertEqual(p.description, "last night's LIVE & more #real")
        self.assertEqual(p.hashtags, ["real"])

    def test_telegram_stream_parser_unescapes(self):
        from platforms.telegram import scraper

        class R:
            status_code = 200
            text = ('<div class="tgme_widget_message js-widget_message" data-post="chan/5">'
                    '<div class="tgme_widget_message_text js-message_text">couldn&#39;t<br/>stop</div>'
                    '<span class="tgme_widget_message_views">1.2K</span></div></div></div>')

        class C:
            def get(self, *a, **k):
                return R()

        _, posts = scraper._fetch_telegram_stream("chan", C())
        self.assertEqual(posts[0]["description"], "couldn't\nstop")


class UsernameWhitespaceTests(StandsBase):
    def test_tab_in_username_rejected(self):
        labels = {"profile_id": Profile.objects.create(name="P").id, "owner_id": Owner.objects.create(name="O").id,
                  "group_id": AccountGroup.objects.create(name="G").id, "country_id": Country.objects.create(name="C").id}
        r = self.post(f"/api/accounts/topics/{self.s1.id}/new-accounts/", {
            "items": [{"username": "dmitry\thttps://www.tiktok.com/@dmitry", "platform": "tiktok"},
                      {"username": "dmitry", "platform": "tiktok"}], **labels,
        })
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["created"], 1, r.data)
        self.assertEqual(len(r.data["errors"]), 1)
        self.assertIn("пробел", r.data["errors"][0])
        self.assertFalse(Account.objects.filter(username__contains="\t").exists())
