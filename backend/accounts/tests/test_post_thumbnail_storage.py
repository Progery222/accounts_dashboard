import tempfile
from unittest.mock import patch

from django.test import TestCase, override_settings

from accounts.models import Account, Platform, Post
from accounts.post_thumbnail_storage import (
    ensure_post_thumbnail_after_sync,
    post_has_stored_thumbnail,
    serve_post_thumbnail_response,
)


class PostThumbnailStorageTests(TestCase):
    def setUp(self):
        self._media_dir = tempfile.mkdtemp(prefix="dashboard_post_thumb_test_")
        self.settings_override = override_settings(MEDIA_ROOT=self._media_dir)
        self.settings_override.enable()
        self.account = Account.objects.create(
            username="thumbuser",
            platform=Platform.TIKTOK,
        )
        self.post = Post.objects.create(
            account=self.account,
            external_id="vid1",
            thumbnail_url="https://cdn.example/cover.jpg",
        )

    def tearDown(self):
        self.settings_override.disable()

    def test_mark_missing_when_scrape_empty(self):
        ensure_post_thumbnail_after_sync(
            self.post,
            self.account,
            scrape_included_thumbnail=True,
            scraped_thumbnail_url="",
        )
        self.post.refresh_from_db()
        self.assertTrue(self.post.thumbnail_missing)

    def test_skip_when_thumbnail_missing_flag(self):
        self.post.thumbnail_missing = True
        self.post.save(update_fields=["thumbnail_missing"])
        with patch("accounts.post_thumbnail_storage.try_download_and_store") as dl:
            ensure_post_thumbnail_after_sync(
                self.post,
                self.account,
                scrape_included_thumbnail=True,
                scraped_thumbnail_url="https://cdn.example/new.jpg",
            )
            dl.assert_not_called()

    @patch("accounts.media_fetch.fetch_image_bytes", return_value=(b"jpeg", "image/jpeg"))
    def test_download_keeps_thumbnail_url(self, _fetch):
        ensure_post_thumbnail_after_sync(
            self.post,
            self.account,
            scrape_included_thumbnail=True,
            scraped_thumbnail_url="https://cdn.example/cover.jpg",
        )
        self.post.refresh_from_db()
        self.assertTrue(post_has_stored_thumbnail(self.post))
        self.assertEqual(self.post.thumbnail_url, "https://cdn.example/cover.jpg")

    @patch("accounts.post_thumbnail_storage._proxy_thumbnail_from_url")
    def test_serve_fallback_to_url(self, proxy):
        from django.http import HttpResponse

        proxy.return_value = HttpResponse(b"ok", content_type="image/jpeg")
        resp = serve_post_thumbnail_response(self.post.pk)
        self.assertEqual(resp.status_code, 200)
        proxy.assert_called_once()
