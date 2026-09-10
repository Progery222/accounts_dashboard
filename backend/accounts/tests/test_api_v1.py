"""РўРµСЃС‚С‹ РІРЅРµС€РЅРµРіРѕ API /api/v1/."""
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from accounts.api_auth import generate_api_key
from accounts.models import Account, Domain, ExternalApiKey, Platform


@override_settings(ROOT_URLCONF="config.urls")
class ExternalApiV1Tests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.domain = Domain.objects.create(slug="extapi", name="Ext API")
        self.acc_reiz = Account.objects.create(
            username="reiz_user",
            platform=Platform.TIKTOK,
            domain=self.domain,
            view_count=100,
            follower_count=10,
        )
        self.acc_other = Account.objects.create(
            username="other_user",
            platform=Platform.TIKTOK,
            view_count=500,
            follower_count=50,
        )
        raw, prefix, key_hash = generate_api_key()
        self.raw_key = raw
        self.api_key = ExternalApiKey.objects.create(
            name="test",
            key_prefix=prefix,
            key_hash=key_hash,
            scopes=["read", "write", "refresh", "export"],
        )

    def _auth(self, key=None):
        return {"HTTP_AUTHORIZATION": f"Bearer {key or self.raw_key}"}

    def test_v1_requires_bearer(self):
        r = self.client.get("/api/v1/summary/")
        self.assertEqual(r.status_code, 401)

    def test_v1_summary_ok(self):
        r = self.client.get("/api/v1/summary/", **self._auth())
        self.assertEqual(r.status_code, 200)
        self.assertGreaterEqual(r.data["account_count"], 2)

    def test_legacy_summary_is_domain_aware(self):
        r = self.client.get("/api/accounts/summary/", HTTP_X_DOMAIN="extapi")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["account_count"], 1)
        self.assertEqual(r.data["view_count"], 100)

    def test_domain_scoped_key(self):
        raw, prefix, key_hash = generate_api_key()
        ExternalApiKey.objects.create(
            name="reiz-only",
            key_prefix=prefix,
            key_hash=key_hash,
            scopes=["read"],
            domain=self.domain,
        )
        r = self.client.get("/api/v1/accounts/", **self._auth(raw))
        self.assertEqual(r.status_code, 200)
        usernames = {row["username"] for row in r.data}
        self.assertEqual(usernames, {"reiz_user"})

    def test_write_scope_required_for_create(self):
        raw, prefix, key_hash = generate_api_key()
        ExternalApiKey.objects.create(
            name="read-only",
            key_prefix=prefix,
            key_hash=key_hash,
            scopes=["read"],
        )
        r = self.client.post(
            "/api/v1/accounts/",
            {"username": "new_u", "platform": "tiktok"},
            format="json",
            **self._auth(raw),
        )
        self.assertEqual(r.status_code, 403)

    def test_accounts_list_with_key(self):
        r = self.client.get("/api/v1/accounts/", **self._auth())
        self.assertEqual(r.status_code, 200)
        self.assertGreaterEqual(len(r.data), 2)

    def test_job_not_found(self):
        r = self.client.get("/api/v1/jobs/999999/", **self._auth())
        self.assertEqual(r.status_code, 404)

    def test_domains_list(self):
        r = self.client.get("/api/v1/domains/", **self._auth())
        self.assertEqual(r.status_code, 200)
        self.assertIn("domains", r.data)

