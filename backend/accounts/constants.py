"""Общие ограничения для модуля accounts."""

from datetime import datetime
from zoneinfo import ZoneInfo

# Маркер в колонке «Обновлён» для только что добавленных аккаунтов (до первого refresh).
NEW_ACCOUNT_UPDATED_AT = datetime(2026, 5, 1, 12, 0, 0, tzinfo=ZoneInfo("Europe/Moscow"))
