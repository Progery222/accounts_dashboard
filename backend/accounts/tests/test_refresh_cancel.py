from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from accounts.models import Account, Platform
from accounts.refresh_cancel import (
    RefreshCancelledError,
    account_refresh_baseline,
    raise_if_refresh_cancel_requested,
    restore_account_refresh_baseline,
)


class RefreshCancelTests(TestCase):
    def test_restore_baseline_keeps_updated_at(self):
        old_ts = timezone.now() - timedelta(days=3)
        acc = Account.objects.create(
            platform=Platform.TELEGRAM,
            username="cancel_test",
            follower_count=100,
            view_count=500,
            updated_at=old_ts,
        )
        baseline = account_refresh_baseline(acc)
        acc.follower_count = 999
        acc.view_count = 1
        acc.updated_at = timezone.now()
        acc.save(update_fields=["follower_count", "view_count", "updated_at"])

        restore_account_refresh_baseline(acc.pk, baseline)
        acc.refresh_from_db()

        self.assertEqual(acc.follower_count, 100)
        self.assertEqual(acc.view_count, 500)
        self.assertEqual(acc.updated_at, old_ts)

    @patch("accounts.refresh_cancel.is_refresh_cancel_requested", return_value=True)
    def test_raise_if_cancel_requested(self, _mock):
        with self.assertRaises(RefreshCancelledError):
            raise_if_refresh_cancel_requested()
