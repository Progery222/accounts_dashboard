from django.test import TestCase

from accounts.models import AutoRefreshState
from accounts.refresh_state import force_stop_auto_refresh
from accounts.warm_run_detail import is_refresh_cancel_requested


class ForceStopAutoRefreshTests(TestCase):
    def test_force_stop_keeps_cancel_flag_for_workers(self):
        st = AutoRefreshState.get()
        st.is_running = True
        st.cancel_requested = False
        st.save(update_fields=["is_running", "cancel_requested", "updated_at"])

        force_stop_auto_refresh(reason="test")

        st.refresh_from_db()
        self.assertFalse(st.is_running)
        self.assertTrue(st.cancel_requested)
        self.assertTrue(is_refresh_cancel_requested())
