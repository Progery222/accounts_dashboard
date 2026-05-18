"""Общий префикс ошибки: views помечают Account.profile_unavailable."""

PROFILE_UNAVAILABLE_MARK = "PROFILE_UNAVAILABLE|"


def is_profile_unavailable_error(message: str) -> bool:
    msg = (message or "").strip()
    if not msg:
        return False
    if msg.startswith(PROFILE_UNAVAILABLE_MARK):
        return True

    text = msg.lower()
    if "обновление не применено" in text:
        return False
    hard_markers = (
        "не найден",
        "не существует",
        "удален",
        "удалён",
        "заблокирован",
        "забанен",
        "not found",
        "doesn't exist",
        "does not exist",
        "deleted",
        "suspended",
        "banned",
        "blocked",
    )
    if any(marker in text for marker in hard_markers):
        return True

    # "недоступен/unavailable" само по себе часто означает временный сбой worker
    # (например, "Worker недоступен"). Считаем это "профиль удалён" только когда
    # сообщение явно про профиль/аккаунт пользователя.
    soft_unavailable = ("недоступен" in text) or ("unavailable" in text)
    if not soft_unavailable:
        return False
    context_markers = (
        "профиль",
        "аккаунт",
        "страница",
        "user",
        "profile",
        "account",
    )
    return any(marker in text for marker in context_markers)


def user_visible_profile_unavailable_error(message: str) -> str:
    if is_profile_unavailable_error(message):
        return message[len(PROFILE_UNAVAILABLE_MARK) :].strip()
    return (message or "").strip()
