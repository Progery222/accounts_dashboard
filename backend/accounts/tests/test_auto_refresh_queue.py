from django.test import SimpleTestCase

from accounts.apps import (
    _auto_refresh_max_queued,
    _enqueue_scheduled_refresh,
    _pop_next_queued_run,
    peek_pending_scheduled_refresh_count,
)


class AutoRefreshQueueTests(SimpleTestCase):
    def setUp(self):
        import accounts.apps as apps_mod

        apps_mod._queued_refresh_runs.clear()

    def test_enqueue_respects_cap(self):
        cap = _auto_refresh_max_queued()
        for _ in range(cap + 2):
            _enqueue_scheduled_refresh(source="scheduler", fast_start=False)
        self.assertEqual(peek_pending_scheduled_refresh_count(), cap)

    def test_pop_fifo(self):
        _enqueue_scheduled_refresh(source="scheduler", fast_start=False)
        _enqueue_scheduled_refresh(source="manual", fast_start=True)
        self.assertEqual(_pop_next_queued_run(), ("scheduler", False))
        self.assertEqual(_pop_next_queued_run(), ("manual", True))
        self.assertIsNone(_pop_next_queued_run())
