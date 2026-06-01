"""Применение нормализованного payload к аккаунту (как Playwright refresh)."""
from __future__ import annotations

import logging

from accounts.models import Account

logger = logging.getLogger(__name__)


def apply_normalized_refresh(account_id: int, payload: dict) -> Account:
    from accounts.views import _refresh_with_retry

    account = Account.objects.get(pk=account_id)
    return _refresh_with_retry(account, scraped=dict(payload))
