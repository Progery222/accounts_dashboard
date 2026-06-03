import tempfile
from unittest.mock import patch

from django.test import TestCase, override_settings

from accounts.avatar_storage import (
    account_has_stored_avatar,
    ensure_account_avatar_after_refresh,
    serve_account_avatar_response,
)
from accounts.models import Account, Platform


class AccountAvatarStorageTests(TestCase):
    def setUp(self):
        self._media_dir = tempfile.mkdtemp(prefix="dashboard_avatar_test_")
        self.settings_override = override_settings(MEDIA_ROOT=self._media_dir)
        self.settings_override.enable()

        Account.objects.create(
            username="noavatar",
            platform=Platform.TIKTOK,
            avatar_url="",
            avatar_missing=False,
        )
        self.with_url = Account.objects.create(
            username="hasurl",
            platform=Platform.TIKTOK,
            avatar_url="https://cdn.example/avatar.jpg",
            avatar_missing=False,
        )

    def tearDown(self):
        self.settings_override.disable()

    def test_mark_missing_when_scrape_reports_empty(self):
        ensure_account_avatar_after_refresh(
            self.with_url,
            scrape_included_avatar=True,
            scraped_avatar_url="",
        )
        self.with_url.refresh_from_db()
        self.assertTrue(self.with_url.avatar_missing)
        self.assertFalse(account_has_stored_avatar(self.with_url))

    def test_keep_existing_url_when_scrape_reports_empty(self):
        ensure_account_avatar_after_refresh(
            self.with_url,
            scrape_included_avatar=True,
            scraped_avatar_url=None,
        )
        self.with_url.refresh_from_db()
        self.assertFalse(self.with_url.avatar_missing)
        self.assertEqual(self.with_url.avatar_url, "https://cdn.example/avatar.jpg")

    def test_skip_when_already_missing(self):
        self.with_url.avatar_missing = True
        self.with_url.save(update_fields=["avatar_missing"])
        with patch("accounts.avatar_storage.try_download_and_store") as dl:
            ensure_account_avatar_after_refresh(
                self.with_url,
                scrape_included_avatar=True,
                scraped_avatar_url="https://cdn.example/new.jpg",
            )
            dl.assert_not_called()

    def test_skip_when_scrape_omits_avatar_field(self):
        with patch("accounts.avatar_storage.try_download_and_store") as dl:
            ensure_account_avatar_after_refresh(
                self.with_url,
                scrape_included_avatar=False,
                scraped_avatar_url=None,
            )
            dl.assert_not_called()

    @patch("accounts.media_fetch.fetch_image_bytes", return_value=(b"jpeg", "image/jpeg"))
    def test_download_keeps_avatar_url(self, _fetch):
        ensure_account_avatar_after_refresh(
            self.with_url,
            scrape_included_avatar=True,
            scraped_avatar_url="https://cdn.example/avatar.jpg",
        )
        self.with_url.refresh_from_db()
        self.assertTrue(account_has_stored_avatar(self.with_url))
        self.assertEqual(self.with_url.avatar_url, "https://cdn.example/avatar.jpg")

    @patch("accounts.avatar_storage._proxy_avatar_from_url")
    def test_serve_fallback_to_url_when_no_file(self, proxy):
        from django.http import HttpResponse

        proxy.return_value = HttpResponse(b"ok", content_type="image/jpeg")
        resp = serve_account_avatar_response(self.with_url.pk)
        self.assertEqual(resp.status_code, 200)
        proxy.assert_called_once()

    def test_serve_404_when_missing_and_no_url(self):
        acc = Account.objects.get(username="noavatar")
        acc.avatar_missing = True
        acc.save(update_fields=["avatar_missing"])
        resp = serve_account_avatar_response(acc.pk)
        self.assertEqual(resp.status_code, 404)
