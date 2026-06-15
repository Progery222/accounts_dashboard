from django.test import SimpleTestCase

from config.http_log_filters import SuppressNoisyPollingFilter


class SuppressNoisyPollingFilterTests(SimpleTestCase):
    def setUp(self):
        self.f = SuppressNoisyPollingFilter()

    def _record(self, name: str, msg: str):
        import logging

        return logging.LogRecord(
            name=name,
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg=msg,
            args=(),
            exc_info=None,
        )

    def test_suppresses_auto_refresh_status(self):
        rec = self._record(
            "django.server",
            '"GET /api/accounts/auto-refresh-status/ HTTP/1.1" 200 3154',
        )
        self.assertFalse(self.f.filter(rec))

    def test_suppresses_refresh_all_status(self):
        rec = self._record(
            "django.server",
            '"GET /api/accounts/refresh-all-status/ HTTP/1.1" 200 512',
        )
        self.assertFalse(self.f.filter(rec))

    def test_keeps_other_requests(self):
        rec = self._record(
            "django.server",
            '"POST /api/accounts/498/refresh/ HTTP/1.1" 200 1024',
        )
        self.assertTrue(self.f.filter(rec))

    def test_keeps_rumble_stderr_style_logs(self):
        rec = self._record("accounts.views", "refresh.scrape_result")
        self.assertTrue(self.f.filter(rec))
