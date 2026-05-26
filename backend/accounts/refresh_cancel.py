"""Остановка refresh / автообновления: не считать прерванные аккаунты обновлёнными."""

from __future__ import annotations

from .models import Account

ACCOUNT_REFRESH_BASELINE_FIELDS = (
    "display_name",
    "avatar_url",
    "bio",
    "follower_count",
    "like_count",
    "view_count",
    "post_count",
    "link_click_count",
    "profile_unavailable",
    "updated_at",
)


class RefreshCancelledError(Exception):
    """Пользователь остановил прогон — изменения аккаунта не применяются."""


def is_refresh_cancel_requested() -> bool:
    from .warm_run_detail import is_refresh_cancel_requested as _impl

    return _impl()


def raise_if_refresh_cancel_requested() -> None:
    if is_refresh_cancel_requested():
        raise RefreshCancelledError("Остановлено пользователем")


def account_refresh_baseline(account: Account) -> dict:
    account.refresh_from_db()
    return {field: getattr(account, field) for field in ACCOUNT_REFRESH_BASELINE_FIELDS}


def restore_account_refresh_baseline(account_id: int, baseline: dict | None) -> None:
    if not baseline:
        return
    Account.objects.filter(pk=account_id).update(**baseline)
