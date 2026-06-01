from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from accounts.tv_emu_config import load_tv_emu_config, save_tv_emu_config


@override_settings(MEDIA_ROOT="/tmp")
class TvEmuConfigApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_get_empty_then_post_and_get(self):
        r = self.client.get("/api/accounts/tv-emu-config/")
        self.assertEqual(r.status_code, 200)
        self.assertIsNone(r.json()["config"])

        payload = {"version": 2, "atom": {}, "pulse": {"platform": {}}, "top": {}}
        r = self.client.post(
            "/api/accounts/tv-emu-config/",
            {"config": payload},
            format="json",
        )
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["ok"])

        self.assertEqual(load_tv_emu_config(), payload)

        r = self.client.get("/api/accounts/tv-emu-config/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["config"], payload)

    def test_save_rejects_non_object(self):
        r = self.client.post("/api/accounts/tv-emu-config/", {"config": "nope"}, format="json")
        self.assertEqual(r.status_code, 400)


class TvEmuConfigFileTests(TestCase):
    def test_roundtrip_file(self):
        cfg = {"version": 2, "note": "test"}
        save_tv_emu_config(cfg)
        self.assertEqual(load_tv_emu_config(), cfg)
