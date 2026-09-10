"""Тесты Origin-gate для UI API."""
from django.test import SimpleTestCase, override_settings
from django.test import RequestFactory

from config.cors_ui import UiApiOriginGateMiddleware, origin_allowed


@override_settings(
    CORS_ALLOW_ALL_ORIGINS=False,
    CORS_ALLOWED_ORIGINS=["https://dashboard-new.atom-farm.com", "http://localhost:5174"],
    CORS_ALLOWED_ORIGIN_REGEXES=[r"^https://[a-z0-9-]+\.atom-farm\.com$"],
)
class OriginAllowedTests(SimpleTestCase):
    def test_allowlist(self):
        self.assertTrue(origin_allowed("https://dashboard-new.atom-farm.com"))
        self.assertTrue(origin_allowed("http://localhost:5174"))
        self.assertTrue(origin_allowed("https://foo.atom-farm.com"))
        self.assertFalse(origin_allowed("https://evil.example.com"))
        self.assertTrue(origin_allowed(""))  # нет Origin — серверный клиент


class UiApiOriginGateTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()

        def ok(_request):
            from django.http import JsonResponse

            return JsonResponse({"ok": True})

        self.mw = UiApiOriginGateMiddleware(ok)

    @override_settings(
        CORS_ALLOW_ALL_ORIGINS=False,
        CORS_ALLOWED_ORIGINS=["https://dashboard-new.atom-farm.com"],
        CORS_ALLOWED_ORIGIN_REGEXES=[],
    )
    def test_blocks_foreign_origin_on_ui_api(self):
        req = self.factory.get("/api/accounts/summary/", HTTP_ORIGIN="https://evil.example.com")
        resp = self.mw(req)
        self.assertEqual(resp.status_code, 403)

    @override_settings(
        CORS_ALLOW_ALL_ORIGINS=False,
        CORS_ALLOWED_ORIGINS=["https://dashboard-new.atom-farm.com"],
        CORS_ALLOWED_ORIGIN_REGEXES=[],
    )
    def test_allows_known_origin(self):
        req = self.factory.get(
            "/api/accounts/summary/",
            HTTP_ORIGIN="https://dashboard-new.atom-farm.com",
        )
        resp = self.mw(req)
        self.assertEqual(resp.status_code, 200)

    @override_settings(
        CORS_ALLOW_ALL_ORIGINS=False,
        CORS_ALLOWED_ORIGINS=["https://dashboard-new.atom-farm.com"],
        CORS_ALLOWED_ORIGIN_REGEXES=[],
    )
    def test_v1_not_gated(self):
        req = self.factory.get("/api/v1/summary/", HTTP_ORIGIN="https://evil.example.com")
        resp = self.mw(req)
        self.assertEqual(resp.status_code, 200)

    def test_no_origin_passes_ui(self):
        req = self.factory.get("/api/accounts/summary/")
        resp = self.mw(req)
        self.assertEqual(resp.status_code, 200)
