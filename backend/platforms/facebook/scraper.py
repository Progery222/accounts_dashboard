from pathlib import Path
from platforms.worker_pool import call_worker

_WORKER = Path(__file__).parent / "worker.py"


def _run_worker(worker_path: Path, payload: dict, platform_name: str) -> dict:
    if not worker_path.exists():
        raise ValueError(
            f"Внутренняя ошибка: worker не найден по пути {worker_path}"
        )
    data = call_worker(worker_path, payload)
    if "error" in data:
        raise ValueError(data["error"])
    if "_posts" not in data:
        data["_posts"] = []
    return data


def fetch_facebook_profile(username: str) -> dict:
    """Данные страницы/профиля Facebook: username, vanity-URL или profile.php?id=…"""
    username = username.lstrip("@")
    return _run_worker(_WORKER, {"username": username}, f"Facebook @{username}")
