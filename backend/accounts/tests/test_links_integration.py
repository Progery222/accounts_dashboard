from unittest.mock import patch

from django.test import SimpleTestCase, TestCase

import integrations.links_client  # noqa: F401

from accounts.models import Account, AccountSnapshot, Platform
from integrations.account_profile_url import account_profile_url
from integrations.links_match import normalize_account_label


class LinksMatchTests(SimpleTestCase):
    def test_tiktok_urls_normalize_same(self):
        a = normalize_account_label("https://www.tiktok.com/@User")
        b = normalize_account_label("http://tiktok.com/@user")
        self.assertEqual(a, b)
        self.assertEqual(a, "tiktok:@user")

    def test_instagram_trailing_slash(self):
        a = normalize_account_label("https://www.instagram.com/foo/")
        b = normalize_account_label("https://instagram.com/foo")
        self.assertEqual(a, b)


class AccountProfileUrlTests(SimpleTestCase):
    def test_tiktok_profile_url(self):
        acc = Account(username="thecapitolverdict", platform=Platform.TIKTOK)
        self.assertEqual(
            account_profile_url(acc),
            "https://www.tiktok.com/@thecapitolverdict",
        )


class ResolveClicksClientTests(SimpleTestCase):
    def test_parse_resolve_matches_by_url_not_row_order(self):
        from integrations.links_client import _parse_resolve_response

        u1 = "https://www.tiktok.com/@first"
        u2 = "https://www.tiktok.com/@second"
        data = {
            "items": [
                {"profile_url": u2, "total_clicks": 200},
                {"profile_url": u1, "total_clicks": 100},
            ],
        }
        out = _parse_resolve_response(data, expected_urls=[u1, u2])
        self.assertEqual(out[u1], 100)
        self.assertEqual(out[u2], 200)

    @patch("integrations.links_client._request")
    def test_resolve_uses_bulk_endpoint_in_batches(self, mock_request):
        import integrations.links_client as lc

        RESOLVE_BATCH_SIZE = lc.RESOLVE_BATCH_SIZE
        resolve_clicks_for_profile_urls = lc.resolve_clicks_for_profile_urls

        urls = [f"https://www.tiktok.com/@u{i}" for i in range(RESOLVE_BATCH_SIZE + 2)]
        mock_request.side_effect = [
            {
                "items": [
                    {"profile_url": u, "total_clicks": i}
                    for i, u in enumerate(urls[:RESOLVE_BATCH_SIZE])
                ],
            },
            {
                "items": [
                    {"profile_url": urls[RESOLVE_BATCH_SIZE], "total_clicks": 999},
                    {"profile_url": urls[RESOLVE_BATCH_SIZE + 1], "total_clicks": 1000},
                ],
            },
        ]
        out = resolve_clicks_for_profile_urls(urls)
        self.assertEqual(mock_request.call_count, 2)
        self.assertEqual(mock_request.call_args_list[0][0][0], "POST")
        self.assertIn("resolve-clicks", mock_request.call_args_list[0][0][1])
        self.assertEqual(out[urls[0]], 0)
        self.assertEqual(out[urls[RESOLVE_BATCH_SIZE]], 999)

    @patch("integrations.links_client.fetch_all_links_index")
    @patch("integrations.links_client._request")
    def test_resolve_falls_back_only_on_405(self, mock_request, mock_index):
        import integrations.links_client as lc

        LinksApiError = lc.LinksApiError
        resolve_clicks_for_profile_urls = lc.resolve_clicks_for_profile_urls

        mock_request.side_effect = LinksApiError("Links API HTTP 405: Method Not Allowed")
        mock_index.return_value = {"tiktok:@user": 7}
        out = resolve_clicks_for_profile_urls(["https://www.tiktok.com/@user"])
        mock_index.assert_called_once()
        self.assertEqual(out["https://www.tiktok.com/@user"], 7)


class RefreshLinkClicksBatchTests(TestCase):
    @patch("integrations.links_sync.build_links_clicks_index")
    def test_refresh_link_clicks_batch_updates_account_and_snapshot(self, mock_index):
        from integrations.links_sync import refresh_link_clicks_batch

        acc = Account.objects.create(username="user1", platform=Platform.TIKTOK)
        mock_index.return_value = {"tiktok:@user1": 55}
        result = refresh_link_clicks_batch([acc])
        acc.refresh_from_db()
        snap = AccountSnapshot.objects.get(account=acc)
        self.assertEqual(result["updated"], 1)
        self.assertEqual(result["changed"], 1)
        self.assertEqual(acc.link_click_count, 55)
        self.assertEqual(snap.link_click_count, 55)

    @patch("integrations.links_sync.build_links_clicks_index")
    def test_refresh_batch_empty_index_raises(self, mock_index):
        from integrations.links_sync import refresh_link_clicks_batch

        acc = Account.objects.create(username="user2", platform=Platform.INSTAGRAM)
        mock_index.return_value = {}
        with self.assertRaises(Exception) as ctx:
            refresh_link_clicks_batch([acc])
        self.assertIn("Links API", str(ctx.exception))


class LinkClickRefreshTests(TestCase):
    def test_apply_refresh_sets_link_clicks_from_api(self):
        acc = Account.objects.create(
            username="thecapitolverdict",
            platform=Platform.TIKTOK,
            link_click_count=0,
        )
        with patch(
            "integrations.links_sync.sync_link_clicks_for_account",
            return_value=42,
        ):
            from accounts.views import _apply_refresh

            _apply_refresh(acc, scraped={
                "display_name": "Test",
                "follower_count": 10,
                "like_count": 0,
                "view_count": 100,
                "post_count": 1,
                "_posts": [],
            })
        acc.refresh_from_db()
        self.assertEqual(acc.link_click_count, 42)
        snap = AccountSnapshot.objects.get(account=acc)
        self.assertEqual(snap.link_click_count, 42)
