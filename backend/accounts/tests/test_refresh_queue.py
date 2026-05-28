from datetime import timedelta

from django.test import SimpleTestCase
from django.utils import timezone

from accounts.models import Account, Platform
from accounts.refresh_queue import (
    interleave_accounts_by_platform,
    order_accounts_for_refresh,
    sort_accounts_by_staleness,
)


def _acc(pk: int, platform: str, *, updated_at):
    return Account(id=pk, username=f"u{pk}", platform=platform, updated_at=updated_at)


class RefreshQueueOrderTests(SimpleTestCase):
    def test_sort_oldest_first(self):
        now = timezone.now()
        a = _acc(1, Platform.TIKTOK, updated_at=now - timedelta(days=10))
        b = _acc(2, Platform.TIKTOK, updated_at=now - timedelta(days=1))
        c = _acc(3, Platform.TIKTOK, updated_at=now - timedelta(days=5))
        ordered = sort_accounts_by_staleness([b, c, a])
        self.assertEqual([x.id for x in ordered], [1, 3, 2])

    def test_interleave_keeps_staleness_within_platform(self):
        now = timezone.now()
        tt_old = _acc(1, Platform.TIKTOK, updated_at=now - timedelta(days=9))
        tt_new = _acc(2, Platform.TIKTOK, updated_at=now - timedelta(days=1))
        ig_old = _acc(3, Platform.INSTAGRAM, updated_at=now - timedelta(days=8))
        ig_new = _acc(4, Platform.INSTAGRAM, updated_at=now - timedelta(days=2))
        ordered = order_accounts_for_refresh([tt_new, ig_new, tt_old, ig_old])
        # раунд 1: самый старый tiktok, самый старый instagram; раунд 2: новее
        self.assertEqual([x.id for x in ordered], [1, 3, 2, 4])

    def test_null_updated_at_first(self):
        now = timezone.now()
        never = _acc(1, Platform.YOUTUBE, updated_at=None)
        recent = _acc(2, Platform.YOUTUBE, updated_at=now)
        ordered = sort_accounts_by_staleness([recent, never])
        self.assertEqual([x.id for x in ordered], [1, 2])
