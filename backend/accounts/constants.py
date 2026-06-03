"""Общие ограничения для модуля accounts (аудитория, съём данных и т.д.)."""

from datetime import datetime
from zoneinfo import ZoneInfo

# Маркер в колонке «Обновлён» для только что добавленных аккаунтов (до первого refresh).
NEW_ACCOUNT_UPDATED_AT = datetime(2026, 5, 1, 12, 0, 0, tzinfo=ZoneInfo("Europe/Moscow"))

# Потолок: сколько подписчиков хранить/подтягивать на один отслеживаемый Account
# (TikTok, Instagram и т.д.). Значение в RefreshScheduleConfig не может его превышать.
MAX_AUDIENCE_FOLLOWERS_PER_TRACKED_ACCOUNT = 100

# Сколько постов подписчика сохранять (защита объёма БД при лимите подписчиков).
MAX_AUDIENCE_POSTS_PER_MEMBER = 35
