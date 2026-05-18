from django.test import SimpleTestCase

from accounts.auto_refresh_csv import (
    collect_auto_refresh_report_rows,
    extract_error_account_ids_from_saved_auto_refresh_csv,
)


class _FakeAccount:
    def __init__(self, pk, platform, username, profile=None):
        self.id = pk
        self.platform = platform
        self.username = username
        self.profile_id = getattr(profile, "id", None) if profile else None
        self.profile = profile
        self.follower_count = 0
        self.like_count = 0
        self.view_count = 0
        self.post_count = 0

    def refresh_from_db(self):
        return None


class AutoRefreshCsvExtractTests(SimpleTestCase):
    def test_collect_fills_not_done_rows(self):
        acc = _FakeAccount(1, "tiktok", "u1")
        rows_in = [{"account_id": 1, "platform": "tiktok", "username": "u1", "status": "успешно"}]
        out = collect_auto_refresh_report_rows(rows_in, [acc])
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["status"], "успешно")

        acc2 = _FakeAccount(2, "instagram", "u2")
        rows_in2 = [None, {"account_id": 2, "platform": "instagram", "username": "u2", "status": "ошибка"}]
        out2 = collect_auto_refresh_report_rows(rows_in2, [acc, acc2])
        self.assertEqual(len(out2), 2)
        self.assertEqual(out2[0]["status"], "не выполнено")
        self.assertEqual(out2[1]["status"], "ошибка")
    def test_extract_ids_from_new_format_with_id_column(self):
        csv = (
            "Параметр;Значение\n"
            "a;b\n"
            "\n"
            "ID аккаунта;Платформа;Username;Статус;x;x;x;x;x;x;x;x;x;x\n"
            "99;instagram;user1;ошибка;;;;;;;;;;\n"
            "100;instagram;user2;успешно;;;;;;;;;;\n"
            "55;tiktok;user3;ошибка;;;;;;;;;;\n"
            "— Справка: суммы\n"
        )
        self.assertEqual(
            extract_error_account_ids_from_saved_auto_refresh_csv(csv),
            [55, 99],
        )

    def test_extract_skips_without_header(self):
        self.assertEqual(
            extract_error_account_ids_from_saved_auto_refresh_csv("a;b\nc;d\n"),
            [],
        )
