from django.test import TestCase

from accounts.models import AutoRefreshState, RefreshAllState
from accounts.warm_run_detail import is_refresh_cancel_requested


class RefreshCancelScopeTests(TestCase):
    def test_stale_refresh_all_cancel_does_not_block(self):
        rr = RefreshAllState.get()
        rr.is_running = False
        rr.cancel_requested = True
        rr.save(update_fields=["is_running", "cancel_requested", "updated_at"])

        auto = AutoRefreshState.get()
        auto.is_running = False
        auto.cancel_requested = False
        auto.save(update_fields=["is_running", "cancel_requested", "updated_at"])

        self.assertFalse(is_refresh_cancel_requested())

    def test_active_refresh_all_cancel_blocks(self):
        rr = RefreshAllState.get()
        rr.is_running = True
        rr.cancel_requested = True
        rr.save(update_fields=["is_running", "cancel_requested", "updated_at"])

        self.assertTrue(is_refresh_cancel_requested())
