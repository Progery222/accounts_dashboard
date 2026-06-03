from django.test import SimpleTestCase

from accounts.telegram_chat_ids import normalize_telegram_chat_ids, telegram_chat_ids_from_config


class TelegramChatIdsTests(SimpleTestCase):
    def test_normalize_list_dedupes(self):
        self.assertEqual(
            normalize_telegram_chat_ids(["123", "123", "456"]),
            ["123", "456"],
        )

    def test_normalize_legacy_string(self):
        self.assertEqual(normalize_telegram_chat_ids("2103509244"), ["2103509244"])

    def test_normalize_rejects_garbage(self):
        self.assertEqual(normalize_telegram_chat_ids(["abc", "123"]), ["123"])

    def test_from_config_prefers_json_list(self):
        cfg = type(
            "Cfg",
            (),
            {
                "auto_refresh_telegram_chat_ids": ["1", "2"],
                "auto_refresh_telegram_chat_id": "9",
            },
        )()
        self.assertEqual(telegram_chat_ids_from_config(cfg), ["1", "2"])

    def test_from_config_legacy_fallback(self):
        cfg = type(
            "Cfg",
            (),
            {
                "auto_refresh_telegram_chat_ids": [],
                "auto_refresh_telegram_chat_id": "2103509244",
            },
        )()
        self.assertEqual(telegram_chat_ids_from_config(cfg), ["2103509244"])
