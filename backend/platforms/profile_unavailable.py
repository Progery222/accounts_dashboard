"""Общий префикс ошибки: views помечают Account.profile_unavailable."""

PROFILE_UNAVAILABLE_MARK = "PROFILE_UNAVAILABLE|"


def is_profile_unavailable_error(message: str) -> bool:
    return (message or "").startswith(PROFILE_UNAVAILABLE_MARK)


def user_visible_profile_unavailable_error(message: str) -> str:
    if is_profile_unavailable_error(message):
        return message[len(PROFILE_UNAVAILABLE_MARK) :].strip()
    return (message or "").strip()
