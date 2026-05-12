"""Общие ограничения для модуля accounts (аудитория, съём данных и т.д.)."""

# Потолок: сколько подписчиков хранить/подтягивать на один отслеживаемый Account
# (TikTok, Instagram и т.д.). Значение в RefreshScheduleConfig не может его превышать.
MAX_AUDIENCE_FOLLOWERS_PER_TRACKED_ACCOUNT = 100

# Сколько постов подписчика сохранять (защита объёма БД при лимите подписчиков).
MAX_AUDIENCE_POSTS_PER_MEMBER = 35
