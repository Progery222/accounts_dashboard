from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import Account, AutoRefreshState, Platform, Profile, RefreshAllState, RefreshScheduleConfig


class RefreshScheduleApiTests(APITestCase):
    def test_enabled_false_string_is_parsed_correctly(self):
        RefreshScheduleConfig.objects.update_or_create(
            pk=1,
            defaults={
                "enabled": True,
                "mode": "interval",
                "interval_hours": 6,
                "times": [],
            },
        )

        response = self.client.post("/api/accounts/schedule/", {"enabled": "false"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(response.data["enabled"])

    def test_auto_refresh_csv_report_always_enabled(self):
        RefreshScheduleConfig.objects.update_or_create(
            pk=1,
            defaults={
                "enabled": False,
                "mode": "interval",
                "interval_hours": 6,
                "times": [],
                "auto_refresh_csv_report": False,
            },
        )

        r = self.client.get("/api/accounts/schedule/")
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertTrue(r.data["auto_refresh_csv_report"])

        r2 = self.client.post(
            "/api/accounts/schedule/",
            {"auto_refresh_csv_report": False},
            format="json",
        )
        self.assertEqual(r2.status_code, status.HTTP_200_OK)
        self.assertTrue(r2.data["auto_refresh_csv_report"])
        cfg = RefreshScheduleConfig.get()
        self.assertTrue(cfg.auto_refresh_csv_report)

    def test_auto_refresh_telegram_settings(self):
        RefreshScheduleConfig.objects.update_or_create(pk=1, defaults={"enabled": False})

        r = self.client.post(
            "/api/accounts/schedule/",
            {
                "auto_refresh_telegram_enabled": True,
                "auto_refresh_telegram_chat_ids": ["123456", "789012"],
            },
            format="json",
        )
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertTrue(r.data["auto_refresh_telegram_enabled"])
        self.assertEqual(r.data["auto_refresh_telegram_chat_ids"], ["123456", "789012"])
        self.assertEqual(r.data["auto_refresh_telegram_chat_id"], "123456")
        self.assertIn("telegram_bot_configured", r.data)
        cfg = RefreshScheduleConfig.get()
        self.assertEqual(cfg.auto_refresh_telegram_chat_ids, ["123456", "789012"])

    def test_auto_refresh_scope_platforms_and_profiles(self):
        RefreshScheduleConfig.objects.update_or_create(
            pk=1,
            defaults={
                "enabled": False,
                "mode": "interval",
                "interval_hours": 6,
                "times": [],
                "auto_refresh_platforms": [],
                "auto_refresh_profile_ids": [],
            },
        )
        r = self.client.post(
            "/api/accounts/schedule/",
            {
                "auto_refresh_platforms": ["tiktok", "facebook", "bad"],
                "auto_refresh_profile_ids": ["none", 5, "5"],
            },
            format="json",
        )
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertEqual(r.data["auto_refresh_platforms"], ["tiktok", "facebook"])
        self.assertEqual(r.data["auto_refresh_profile_ids"], ["none", 5])

        prof = Profile.objects.create(name="P1", color="#fff")
        Account.objects.create(username="tt1", platform=Platform.TIKTOK, profile=prof)
        Account.objects.create(username="ig1", platform=Platform.INSTAGRAM, profile=prof)
        Account.objects.create(username="fb1", platform=Platform.FACEBOOK, profile=prof)

        from accounts.auto_refresh_scope import apply_auto_refresh_scope

        cfg = RefreshScheduleConfig.get()
        cfg.auto_refresh_platforms = ["tiktok", "instagram"]
        cfg.auto_refresh_profile_ids = [prof.id]
        cfg.save(update_fields=["auto_refresh_platforms", "auto_refresh_profile_ids"])

        ids = set(
            apply_auto_refresh_scope(Account.objects.all(), cfg).values_list("username", flat=True),
        )
        self.assertEqual(ids, {"tt1", "ig1"})

    def test_schedule_times_only_four_slots(self):
        RefreshScheduleConfig.objects.update_or_create(
            pk=1,
            defaults={"enabled": False, "mode": "times", "times": ["09:00", "18:00"]},
        )
        r = self.client.get("/api/accounts/schedule/")
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertEqual(r.data["times"], ["18:00"])

        r2 = self.client.post(
            "/api/accounts/schedule/",
            {"times": ["00:00", "03:00", "06:00", "12:00", "18:00", "bad"]},
            format="json",
        )
        self.assertEqual(r2.status_code, status.HTTP_200_OK)
        self.assertEqual(r2.data["times"], ["00:00", "06:00", "12:00", "18:00"])

    def test_auto_refresh_domain_and_group_scope(self):
        from accounts.models import AccountGroup, Domain

        dom_a = Domain.objects.create(name="A", slug="a", color="#111111")
        dom_b = Domain.objects.create(name="B", slug="b", color="#222222")
        grp = AccountGroup.objects.create(name="G1", color="#fff")
        Account.objects.create(username="a1", platform=Platform.TIKTOK, domain=dom_a, group=grp)
        Account.objects.create(username="b1", platform=Platform.TIKTOK, domain=dom_b)
        Account.objects.create(username="n1", platform=Platform.TIKTOK)

        r = self.client.post(
            "/api/accounts/schedule/",
            {
                "auto_refresh_domain_ids": [dom_a.id, "none"],
                "auto_refresh_group_ids": [grp.id],
            },
            format="json",
        )
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertEqual(r.data["auto_refresh_domain_ids"], [dom_a.id, "none"])
        self.assertEqual(r.data["auto_refresh_group_ids"], [grp.id])

        from accounts.auto_refresh_scope import apply_auto_refresh_scope

        cfg = RefreshScheduleConfig.get()
        ids = set(
            apply_auto_refresh_scope(Account.objects.all(), cfg).values_list("username", flat=True),
        )
        self.assertEqual(ids, {"a1"})

    def test_refresh_warm_enabled_toggle(self):
        RefreshScheduleConfig.objects.update_or_create(
            pk=1,
            defaults={
                "enabled": False,
                "mode": "interval",
                "interval_hours": 6,
                "times": [],
                "refresh_warm_enabled": True,
            },
        )
        r = self.client.get("/api/accounts/schedule/")
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertTrue(r.data.get("refresh_warm_enabled"))

        r2 = self.client.post(
            "/api/accounts/schedule/",
            {"refresh_warm_enabled": False},
            format="json",
        )
        self.assertEqual(r2.status_code, status.HTTP_200_OK)
        self.assertFalse(r2.data["refresh_warm_enabled"])

    def test_auto_refresh_status_includes_run_detail(self):
        r = self.client.get("/api/accounts/auto-refresh-status/")
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertIn("run_detail", r.data)
        self.assertIsInstance(r.data["run_detail"], dict)
        self.assertIn("skip_recent_hours_config", r.data)
        self.assertIn("active_pipeline", r.data)

    def test_auto_refresh_status_merges_refresh_all_running(self):
        """Пока идёт refresh_all, тот же endpoint что и для авто — is_running true и прогресс с RefreshAllState."""
        rr = RefreshAllState.get()
        rr.is_running = True
        rr.cancel_requested = False
        rr.total_accounts = 40
        rr.processed_accounts = 12
        rr.success_accounts = 10
        rr.failed_accounts = 0
        rr.run_detail = {"items": [], "worker_count": 2}
        rr.save(
            update_fields=[
                "is_running", "cancel_requested", "total_accounts", "processed_accounts",
                "success_accounts", "failed_accounts", "run_detail", "updated_at",
            ],
        )
        auto = AutoRefreshState.get()
        auto.is_running = False
        auto.save(update_fields=["is_running", "updated_at"])

        r = self.client.get("/api/accounts/auto-refresh-status/")
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertTrue(r.data["is_running"])
        self.assertEqual(r.data["active_pipeline"], "refresh_all")
        self.assertEqual(r.data["processed_accounts"], 12)
        self.assertEqual(r.data["total_accounts"], 40)
        self.assertEqual(r.data["source"], "refresh_all")

    def test_auto_refresh_last_error_ids_returns_sorted_unique(self):
        st = AutoRefreshState.get()
        st.last_auto_refresh_error_account_ids = [7, 3, 7, "12", "bad", None]
        st.save(update_fields=["last_auto_refresh_error_account_ids", "updated_at"])

        r = self.client.get("/api/accounts/auto-refresh-last-error-ids/")
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertEqual(r.data["ids"], [3, 7, 12])
        self.assertEqual(r.data["count"], 3)

    def test_account_delta_period_days_get_and_post(self):
        RefreshScheduleConfig.objects.update_or_create(
            pk=1,
            defaults={
                "enabled": False,
                "mode": "interval",
                "interval_hours": 6,
                "times": [],
                "account_delta_period_days": 1,
            },
        )
        r = self.client.get("/api/accounts/schedule/")
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertEqual(r.data.get("account_delta_period_days"), 1)

        r2 = self.client.post("/api/accounts/schedule/", {"account_delta_period_days": 7}, format="json")
        self.assertEqual(r2.status_code, status.HTTP_200_OK)
        self.assertEqual(r2.data.get("account_delta_period_days"), 7)

        r3 = self.client.post("/api/accounts/schedule/", {"account_delta_period_days": 99}, format="json")
        self.assertEqual(r3.status_code, status.HTTP_200_OK)
        self.assertEqual(r3.data.get("account_delta_period_days"), 1)
