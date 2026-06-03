from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from accounts.auto_refresh_csv import extract_auto_refresh_status_counts
from accounts.telegram_report import (
    build_auto_refresh_telegram_text,
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
        )
        self.assertIn("Успешно (данные изменились): 1", text)
        self.assertIn("Успешно (без изменений): 1", text)
        self.assertIn("Пропущено: 1", text)
        self.assertIn("Ошибки: 1", text)

    def test_zero_accounts_message(self):
        text = build_auto_refresh_telegram_text(
            rows=[],
            started_at=timezone.now(),
            finished_at=timezone.now(),
            total_accounts=0,
        )
        self.assertIn("Нет аккаунтов для обновления", text)

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
