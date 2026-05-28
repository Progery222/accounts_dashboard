import json
import os
import subprocess
import sys
import time
from pathlib import Path

from platforms.worker_pool import call_worker

_WORKER = Path(__file__).parent / "worker.py"


def _facebook_refresh_timeout_sec() -> float:
    raw = (os.environ.get("FACEBOOK_REFRESH_TIMEOUT_SEC") or "900").strip()
    try:
        return max(60.0, float(raw))
    except ValueError:
        return 900.0


def _facebook_use_daemon_pool() -> bool:
    """По умолчанию демон (как prewarm): иначе --once убивает тот же facebook_from_state."""
    raw = os.environ.get("FACEBOOK_USE_DAEMON_WORKER", "1").strip().lower()
    if raw in {"0", "false", "no", "off"}:
        return False
    return raw in {"1", "true", "yes", "on", ""}


def _facebook_daemon_alive(worker_path: Path) -> bool:
    from platforms.worker_pool import _GLOBAL_LOCK, _HANDLES, pool_storage_key

    key = pool_storage_key(worker_path)
    with _GLOBAL_LOCK:
        handle = _HANDLES.get(key)
        if handle is None or handle.proc.poll() is not None:
            return False
        return handle._browser_ready.is_set()


def _run_worker_oneshot(worker_path: Path, payload: dict) -> dict:
    """Один процесс --once: не попадает в reconcile --daemon и не зависает от чужого runserver."""
    from platforms.worker_pool import (
        _backend_dir_for_worker,
        _chrome_roots_for_worker,
        _compose_worker_env,
        _kill_chromium_after_worker,
        call_worker,
    )

    if not worker_path.exists():
        raise ValueError(f"Внутренняя ошибка: worker не найден по пути {worker_path}")
    if _facebook_daemon_alive(worker_path):
        return call_worker(
            worker_path,
            payload,
            timeout_sec=_facebook_refresh_timeout_sec(),
        )
    backend_root = str(_backend_dir_for_worker(worker_path))
    _kill_chromium_after_worker(_chrome_roots_for_worker(worker_path))
    time.sleep(0.45)
    env = _compose_worker_env(backend_root)
    cmd = [
        sys.executable,
        str(worker_path.resolve()),
        "--once",
        json.dumps(payload, ensure_ascii=False),
    ]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=_facebook_refresh_timeout_sec(),
            cwd=backend_root,
            env=env,
        )
    except subprocess.TimeoutExpired as exc:
        raise ValueError(
            f"Таймаут Facebook worker ({int(_facebook_refresh_timeout_sec())} с). "
            "Закройте зависший Chrome (TikStatsChromeProfile) и повторите."
        ) from exc
    if proc.stderr:
        for line in proc.stderr.splitlines():
            if line.strip():
                print(line, file=sys.stderr)
    lines = [ln for ln in (proc.stdout or "").splitlines() if ln.strip()]
    if not lines:
        raise ValueError(
            f"Worker не вернул ответ: {(proc.stderr or '')[:500]}"
        )
    try:
        data = json.loads(lines[-1].strip())
    except Exception as exc:
        raise ValueError("Ошибка парсинга ответа worker") from exc
    if isinstance(data, dict) and "error" in data:
        raise ValueError(data["error"])
    return data


def _run_worker(worker_path: Path, payload: dict, platform_name: str) -> dict:
    if not worker_path.exists():
        raise ValueError(
            f"Внутренняя ошибка: worker не найден по пути {worker_path}"
        )
    if _facebook_use_daemon_pool():
        data = call_worker(worker_path, payload, timeout_sec=_facebook_refresh_timeout_sec())
    else:
        data = _run_worker_oneshot(worker_path, payload)
    if "error" in data:
        err = data["error"]
        from platforms.facebook.rate_limit import (
            is_facebook_rate_limited_error,
            shutdown_facebook_worker,
        )

        if is_facebook_rate_limited_error(ValueError(err)):
            shutdown_facebook_worker()
        raise ValueError(err)
    if "_posts" not in data:
        data["_posts"] = []
    return data


def fetch_facebook_profile(username: str) -> dict:
    """Данные страницы/профиля Facebook: username, vanity-URL или profile.php?id=…"""
    username = username.lstrip("@")
    return _run_worker(_WORKER, {"username": username}, f"Facebook @{username}")
