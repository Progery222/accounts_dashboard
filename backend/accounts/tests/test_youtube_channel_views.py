from django.test import SimpleTestCase, TestCase

from accounts.models import Account, Platform, Post
from accounts.views import _apply_post_aggregates_to_account
from platforms.youtube.scraper import _parse_count, _fetch_youtube_scrape


class YouTubeParseCountTests(SimpleTestCase):
    def test_parse_channel_view_count_text(self):
        self.assertEqual(_parse_count("1,011,547 views"), 1_011_547)
        self.assertEqual(_parse_count("1.03K subscribers"), 1030)
        self.assertEqual(_parse_count("2.4M views"), 2_400_000)


class YouTubeChannelViewsScrapeTests(SimpleTestCase):
    def test_scrape_reads_channel_view_count_from_about_html(self):
        channel_html = (
            '<meta property="og:title" content="Асель Исакова">'
            '"channelId":"UCabcdefghijklmnopqrstuv"'
        )
        about_html = (
            '{"subscriberCountText":"1.03K subscribers",'
            '"viewCountText":"1,011,547 views",'
            '"joinedDateText":{"content":"Joined Aug 31, 2026"}}'
        )

        class _Resp:
            def __init__(self, text, status_code=200):
                self.text = text
                self.status_code = status_code

            def raise_for_status(self):
                return None

        class _Client:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def get(self, url, *args, **kwargs):
                if str(url).rstrip("/").endswith("/about"):
                    return _Resp(about_html)
                return _Resp(channel_html)

        from unittest.mock import patch

        with patch("platforms.youtube.scraper.HttpClient", return_value=_Client()):
            with patch("platforms.youtube.scraper._fetch_youtube_rss", return_value=[]):
                data = _fetch_youtube_scrape("АсельИсакова-т4ц")

        self.assertEqual(data["follower_count"], 1030)
        self.assertEqual(data["view_count"], 1_011_547)


class YouTubeAggregateKeepsChannelViewsTests(TestCase):
    def test_youtube_keeps_scraped_channel_views_over_post_sum(self):
        account = Account.objects.create(
            username="yt_views",
            platform=Platform.YOUTUBE,
            view_count=1_011_547,  # already applied from scrape
            post_count=2,
        )
        Post.objects.create(account=account, external_id="a", view_count=100_000)
        Post.objects.create(account=account, external_id="b", view_count=50_000)

        _apply_post_aggregates_to_account(
            account,
            {"view_count": 900_000, "like_count": 0, "post_count": 2},
        )
        self.assertEqual(account.view_count, 1_011_547)
