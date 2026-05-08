from pathlib import Path
from platforms.worker_pool import call_worker
from platforms.profile_unavailable import PROFILE_UNAVAILABLE_MARK

_WORKER = Path(__file__).parent / "worker.py"


def _raise_x_profile_unavailable(username: str, detail: str = "профиль не найден или недоступен") -> None:
    u = (username or "").lstrip("@")
    raise ValueError(f"{PROFILE_UNAVAILABLE_MARK}X @{u}: {detail}")


def _message_indicates_x_profile_unavailable(message: str) -> bool:
    low = (message or "").lower()
    markers = (
        "this account doesn",
        "this account does not exist",
        "account doesn",
        "profile x @",
        "профиль x @",
        "профиль не найден",
        "user not found",
        "not found",
        "suspended",
        "account suspended",
    )
    return any(marker in low for marker in markers)


def _run_worker(worker_path: Path, payload: dict, platform_name: str) -> dict:
    if not worker_path.exists():
        raise ValueError(
            f"Внутренняя ошибка: worker не найден по пути {worker_path}"
        )
    data = call_worker(worker_path, payload)
    if "error" in data:
        msg = str(data["error"])
        if _message_indicates_x_profile_unavailable(msg):
            _raise_x_profile_unavailable(payload.get("username", ""), "профиль не найден или недоступен на площадке.")
        raise ValueError(msg)
    if "_posts" not in data:
        data["_posts"] = []
    return data


def fetch_x_profile(username: str) -> dict:
    """Fetch X (Twitter) profile data via Playwright subprocess."""
    username = username.lstrip("@")
    return _run_worker(_WORKER, {"username": username}, f"X @{username}")
