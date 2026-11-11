from datetime import timedelta
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from accounts.models import Account, AccountSnapshot, Owner, Platform, Profile
from accounts.telegram_report import (
    build_auto_refresh_telegram_text,
    collect_profile_owner_stats,
    should_send_auto_refresh_telegram,
)


class TelegramTextTests(SimpleTestCase):
    def test_build_text_counts(self):
        rows = [
            {"status": "успешно"},
            {"status": "успешно (данные без изменений)"},
            {"status": "пропущен"},
            {"status": "ошибка"},
        ]
        started = timezone.now()
        finished = started
        text = build_auto_refresh_telegram_text(
            rows=rows,
            started_at=started,
            finished_at=finished,
            total_accounts=4,
            profile_stats=[],
            owner_stats=[],
        )
        self.assertIn("Успешно (данные изменились): <b>1</b>", text)
        self.assertIn("Успешно (без изменений): <b>1</b>", text)
        self.assertIn("Пропущено: <b>1</b>", text)
        self.assertIn("Ошибки: <b>1</b>", text)

    def test_zero_accounts_message(self):
        text = build_auto_refresh_telegram_text(
            rows=[],
            started_at=timezone.now(),
            finished_at=timezone.now(),
            total_accounts=0,
            profile_stats=[],
            owner_stats=[],
        )
        self.assertIn("Нет аккаунтов для обновления", text)

    def test_profile_owner_blocks_alphabet_and_metrics(self):
        text = build_auto_refresh_telegram_text(
            rows=[],
            started_at=timezone.now(),
            finished_at=timezone.now(),
            total_accounts=1,
            profile_stats=[
                ("Music", {
                    "views": 1000, "likes": 10, "followers": 5, "posts": 2,
                    "views_d": 100, "likes_d": 1, "followers_d": 0, "posts_d": 1,
                }),
                ("Отдел трафика", {
                    "views": 2000, "likes": 20, "followers": 7, "posts": 3,
                    "views_d": 50, "likes_d": 2, "followers_d": 1, "posts_d": 0,
                }),
            ],
            owner_stats=[
                ("Александр", {
                    "views": 500, "likes": 5, "followers": 2, "posts": 1,
                    "views_d": 10, "likes_d": 0, "followers_d": 0, "posts_d": 0,
                }),
                ("Без пользователя", {
                    "views": 100, "likes": 1, "followers": 1, "posts": 1,
                    "views_d": 0, "likes_d": 0, "followers_d": 0, "posts_d": 0,
                }),
            ],
        )
        self.assertIn("📁 <b>Профили</b>", text)
        self.assertIn("👤 <b>Пользователи</b>", text)
        self.assertIn("• <b>Music</b>", text)
        self.assertIn("• <b>Отдел трафика</b>", text)
        self.assertIn("👁 Просмотры: <b>1 000</b>  <i>прирост +100</i>", text)
        self.assertIn("❤️ Лайки: <b>10</b>  <i>прирост +1</i>", text)
        self.assertIn("👥 Подписчики: <b>5</b>  <i>прирост 0</i>", text)
        self.assertIn("📝 Публикации: <b>2</b>  <i>прирост +1</i>", text)
        self.assertLess(text.index("• <b>Music</b>"), text.index("• <b>Отдел трафика</b>"))
        self.assertLess(text.index("• <b>Александр</b>"), text.index("• <b>Без пользователя</b>"))

    def test_should_not_send_on_cancel(self):
        self.assertFalse(
            should_send_auto_refresh_telegram(
                run_was_cancelled=True,
                last_error="",
            ),
        )
        self.assertFalse(
            should_send_auto_refresh_telegram(
                run_was_cancelled=False,
                last_error="Автообновление остановлено пользователем.",
            ),
        )

    def test_should_not_send_instant_empty_run(self):
        started = timezone.now()
        self.assertFalse(
            should_send_auto_refresh_telegram(
                run_was_cancelled=False,
                last_error="",
                report_rows=[],
                started_at=started,
                finished_at=started,
                run_detail={"items": [{"status": "queued"}]},
            ),
        )


class TelegramStatsCollectTests(TestCase):
    def test_collect_sorted_with_deltas(self):
        music = Profile.objects.create(name="Music")
        traffic = Profile.objects.create(name="Отдел трафика")
        alex = Owner.objects.create(name="Александр")
        a1 = Account.objects.create(
            username="u1",
            platform=Platform.TIKTOK,
            profile=music,
            owner=alex,
            view_count=1100,
            like_count=11,
            follower_count=6,
            post_count=3,
        )
        Account.objects.create(
            username="u2",
            platform=Platform.TIKTOK,
            profile=traffic,
            view_count=200,
            like_count=2,
            follower_count=1,
            post_count=1,
        )
        yesterday = timezone.localdate() - timedelta(days=1)
        AccountSnapshot.objects.create(
            account=a1,
            date=yesterday,
            view_count=1000,
            like_count=10,
            follower_count=5,
            post_count=2,
        )
        profiles, owners = collect_profile_owner_stats()
        names = [n for n, _ in profiles]
        self.assertEqual(names, ["Music", "Отдел трафика"])
        music_st = dict(profiles)["Music"]
        self.assertEqual(music_st["views"], 1100)
        self.assertEqual(music_st["views_d"], 100)
        owner_names = [n for n, _ in owners]
        self.assertIn("Александр", owner_names)
        self.assertIn("Без пользователя", owner_names)
        self.assertLess(owner_names.index("Александр"), owner_names.index("Без пользователя"))


class TelegramApiTests(TestCase):
    def test_telegram_test_endpoint_requires_token(self):
        from rest_framework.test import APIClient

        client = APIClient()
        with patch(
            "accounts.telegram_report.send_telegram_test_message",
            side_effect=RuntimeError("TELEGRAM_BOT_TOKEN не задан"),
        ):
            r = client.post(
                "/api/accounts/schedule/telegram-test/",
                {"chat_id": "123"},
                format="json",
            )
        self.assertEqual(r.status_code, 400)

    @patch("accounts.telegram_report.send_telegram_message")
    def test_send_report(self, mock_msg):
        from accounts.telegram_report import send_auto_refresh_telegram_report

        cfg = MagicMock(
            auto_refresh_telegram_chat_ids=["99"],
            auto_refresh_telegram_chat_id="99",
        )
        with patch("accounts.telegram_report.send_telegram_document"):
            send_auto_refresh_telegram_report(
                config=cfg,
                text="hi",
                csv_body="a;b\n1;2",
                filename="t.csv",
            )
        mock_msg.assert_called_once()

    @patch("accounts.telegram_report.send_telegram_message")
    def test_send_report_multiple_chats(self, mock_msg):
        from accounts.telegram_report import send_auto_refresh_telegram_report

        cfg = MagicMock(
            auto_refresh_telegram_chat_ids=["11", "22"],
            auto_refresh_telegram_chat_id="11",
        )
        with patch("accounts.telegram_report.send_telegram_document"):
            send_auto_refresh_telegram_report(
                config=cfg,
                text="hi",
                csv_body="a;b\n1;2",
                filename="t.csv",
            )
        self.assertEqual(mock_msg.call_count, 2)
