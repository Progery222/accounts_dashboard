"""Доступ к БД дашборда из worker-процессов (Django ORM после setup)."""


def existing_audience_usernames_for_dashboard_account(account_id: int) -> set[str]:
    """Нормализованные ники подписчиков, уже связанных с аккаунтом `accounts.Account`."""
    import os

    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    import django

    django.setup()
    from accounts.models import AudienceMember

    return {
        str(u or "").strip().lstrip("@").lower()
        for u in AudienceMember.objects.filter(memberships__account_id=account_id).values_list(
            "username",
            flat=True,
        )
    }
