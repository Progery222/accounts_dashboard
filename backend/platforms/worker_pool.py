import atexit
import json
import os
import queue
import subprocess
import sys
import threading
import time
from pathlib import Path


def _backend_dir_for_worker(worker_path: Path) -> Path:
    """
    Каталог с manage.py (обычно backend/). Нужен как cwd subprocess: иначе
    `python .../platforms/threads/worker.py` кладёт в sys.path только .../threads,
    и строка `from platforms...` падает с ImportError до любого ответа в stdout.
    """
    p = worker_path.resolve().parent
    for _ in range(12):
        if (p / "manage.py").exists():
            return p
        if p == p.parent:
            break
        p = p.parent
    raise RuntimeError(
        f"Не найден каталог Django (manage.py) над {worker_path}. "
        "Запускайте manage.py из backend/."
    )


def _worker_subprocess_env(backend_root: str) -> dict:
    """
    cwd=backend недостаточно: при `python .../threads/worker.py` Python кладёт в sys.path
    только каталог скрипта, а не cwd — без PYTHONPATH пакет `platforms` не импортируется.
    """
    env = os.environ.copy()
    prev = (env.get("PYTHONPATH") or "").strip()
    if prev:
        parts = [p for p in prev.split(os.pathsep) if p]
        if backend_root not in parts:
            env["PYTHONPATH"] = backend_root + os.pathsep + prev
    else:
        env["PYTHONPATH"] = backend_root
    return env


def _compose_worker_env(backend_root: str) -> dict:
    """
    Env дочернего воркера: каталог профиля / headless как у дашборда (AccountsStats,
    refresh, съём аудитории) — см. ACCOUNTS_BROWSER_* в settings, задаются через
    backend/config/worker_accounts.env.
    """
    env = _worker_subprocess_env(backend_root)
    try:
        from django.conf import settings as dj_settings
    except Exception:
        return env

    prof = getattr(dj_settings, "ACCOUNTS_BROWSER_PROFILE_DIR", None)
    if prof is not None:
        p = Path(prof)
        p.mkdir(parents=True, exist_ok=True)
        env["BROWSER_PROFILE_DIR"] = str(p)
    hl = getattr(dj_settings, "ACCOUNTS_BROWSER_HEADLESS", None)
    if hl is not None:
        env["BROWSER_HEADLESS"] = "true" if hl else "false"
    threads_nav = (os.environ.get("THREADS_NAV_TIMEOUT_MS") or "").strip()
    if not threads_nav:
        threads_nav = "60000"
    env["THREADS_NAV_TIMEOUT_MS"] = threads_nav
    auth_nav = (os.environ.get("AUTH_NAV_TIMEOUT_MS") or "").strip()
    if auth_nav:
        env["AUTH_NAV_TIMEOUT_MS"] = auth_nav
    return env


def pool_storage_key(worker_path: Path) -> str:
    return str(worker_path.resolve())


class _WorkerHandle:
    def __init__(self, worker_path: Path):
        self.worker_path = worker_path
        self.lock = threading.Lock()
        self._cwd = str(_backend_dir_for_worker(worker_path))
        child_env = _compose_worker_env(self._cwd)
        self.proc = subprocess.Popen(
            [sys.executable, str(worker_path), "--daemon"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            cwd=self._cwd,
            env=child_env,
        )
        self._stderr_thread = threading.Thread(target=self._drain_stderr, daemon=True)
        self._stderr_thread.start()
        self._stdout_queue: queue.Queue[str | None] = queue.Queue()
        self._stdout_thread = threading.Thread(target=self._drain_stdout, daemon=True)
        self._stdout_thread.start()

    def _drain_stderr(self) -> None:
        if self.proc.stderr is None:
            return
        for line in self.proc.stderr:
            if line:
                print(line, end="", file=sys.stderr)

    def _drain_stdout(self) -> None:
        if self.proc.stdout is None:
            self._stdout_queue.put(None)
            return
        for line in self.proc.stdout:
            self._stdout_queue.put(line)
        # EOF marker: worker exited or pipe closed.
        self._stdout_queue.put(None)

    def call(self, payload: dict, *, timeout_sec: float | None = None) -> dict:
        if self.proc.poll() is not None:
            raise ValueError("Фоновый worker завершился, попробуйте обновить еще раз")
        if self.proc.stdin is None or self.proc.stdout is None:
            raise ValueError("Worker недоступен")

        with self.lock:
            self.proc.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
            self.proc.stdin.flush()
            try:
                if timeout_sec is not None and timeout_sec > 0:
                    line = self._stdout_queue.get(timeout=timeout_sec)
                else:
                    line = self._stdout_queue.get()
            except queue.Empty:
                raise ValueError(
                    f"Таймаут ожидания ответа worker ({int(timeout_sec)}с). "
                    "Попробуйте ещё раз."
                )
        if not line:
            raise ValueError("Worker не вернул ответ")
        try:
            data = json.loads(line.strip())
        except Exception:
            raise ValueError("Ошибка парсинга ответа worker")
        if "error" in data:
            raise ValueError(data["error"])
        return data

    def close(self) -> None:
        """
        Корректно завершить процесс воркера. Только ``terminate()`` без ``wait`` оставляет
        дочерний Chromium в доке (особенно при быстром пересоздании пула после ошибки).
        """
        proc = getattr(self, "proc", None)
        if proc is None:
            return
        try:
            if proc.poll() is not None:
                try:
                    proc.wait(timeout=2.0)
                except Exception:
                    pass
            else:
                try:
                    proc.terminate()
                except Exception:
                    pass
                try:
                    proc.wait(timeout=8.0)
                except subprocess.TimeoutExpired:
                    try:
                        proc.kill()
                    except Exception:
                        pass
                    try:
                        proc.wait(timeout=4.0)
                    except Exception:
                        pass
        except Exception:
            pass
        _kill_orphan_chromium_after_worker()


def _kill_orphan_chromium_after_worker() -> None:
    try:
        from platforms.worker_utils import kill_all_accounts_profile_chrome

        kill_all_accounts_profile_chrome(cleanup_artifacts=False)
    except Exception:
        pass


_HANDLES: dict[str, _WorkerHandle] = {}
_GLOBAL_LOCK = threading.Lock()


def _is_recoverable_playwright_error(message: str) -> bool:
    msg = (message or "").lower()
    markers = (
        "target page, context or browser has been closed",
        "browser has been closed",
        "context has been closed",
        "page has been closed",
        "вкладка tiktok закрыта",
        "worker завершился",
        "worker не вернул ответ",
        "таймаут ожидания ответа worker",
    )
    return any(m in msg for m in markers)


def call_worker(
    worker_path: Path,
    payload: dict,
    *,
    timeout_sec: float | None = None,
) -> dict:
    """
    До 3 попыток при «пустом stdout» / закрытом браузере — при refresh_all по многим
    аккаунтам один сбой не должен навсегда ломать пул.
    """
    key = pool_storage_key(worker_path)
    last_exc: BaseException | None = None
    for _attempt in range(3):
        closed_dead_worker = False
        with _GLOBAL_LOCK:
            handle = _HANDLES.get(key)
            dead = handle is None or handle.proc.poll() is not None
            if dead:
                if handle is not None:
                    try:
                        handle.close()
                    except Exception:
                        pass
                    closed_dead_worker = True
                if closed_dead_worker or _attempt > 0:
                    _kill_orphan_chromium_after_worker()
                    time.sleep(0.45)
                handle = _WorkerHandle(worker_path)
                _HANDLES[key] = handle
        try:
            return handle.call(payload, timeout_sec=timeout_sec)
        except Exception as exc:
            last_exc = exc
            if not _is_recoverable_playwright_error(str(exc)):
                raise
            # Не пересоздаём процесс «на всякий случай» после успешного первого вызова:
            # иначе при одной ошибке пользователь видит второе окно браузера.
            # Снимаем зависший/битый воркер из пула — следующая итерация поднимет новый.
            popped = False
            with _GLOBAL_LOCK:
                h = _HANDLES.get(key)
                if h is not None:
                    try:
                        h.close()
                    except Exception:
                        pass
                    _HANDLES.pop(key, None)
                    popped = True
            if popped:
                _kill_orphan_chromium_after_worker()
                time.sleep(0.85)
    assert last_exc is not None
    raise last_exc


def ensure_worker(worker_path: Path) -> None:
    """
    Ensure daemon worker process is started and kept in pool.
    Used for pre-warming browser windows/contexts before bulk refresh.
    """
    key = pool_storage_key(worker_path)
    closed_dead = False
    with _GLOBAL_LOCK:
        handle = _HANDLES.get(key)
        if handle is None or handle.proc.poll() is not None:
            if handle is not None:
                try:
                    handle.close()
                except Exception:
                    pass
                closed_dead = True
            _HANDLES[key] = _WorkerHandle(worker_path)
    if closed_dead:
        time.sleep(0.5)
        _kill_orphan_chromium_after_worker()


@atexit.register
def _shutdown_workers() -> None:
    """При выходе Python закрыть дочерние worker-процессы. Обход: PLAYWRIGHT_POOL_SKIP_ATEXIT=1."""
    if os.getenv("PLAYWRIGHT_POOL_SKIP_ATEXIT", "").strip().lower() in {"1", "true", "yes", "on"}:
        return
    for h in list(_HANDLES.values()):
        h.close()


def shutdown_all_workers() -> None:
    """Закрыть все демоны Playwright — после сброса сессии в настройках."""
    with _GLOBAL_LOCK:
        for h in list(_HANDLES.values()):
            try:
                h.close()
            except Exception:
                pass
        _HANDLES.clear()
    _kill_orphan_chromium_after_worker()


def shutdown_playwright_pool_aggressive(*, sleep_sec: float = 0.55) -> None:
    """
    Закрыть пул демонов и снять все Chromium профиля AccountsStats.
    Двойной проход kill нужен на Windows: после terminate() воркера дочерний Chrome
    часто остаётся в доке ещё сотни миллисекунд.
    """
    shutdown_all_workers()
    try:
        from platforms.worker_utils import kill_all_accounts_profile_chrome

        kill_all_accounts_profile_chrome(cleanup_artifacts=True)
    except Exception:
        pass
    if sleep_sec > 0:
        time.sleep(sleep_sec)
        try:
            from platforms.worker_utils import kill_all_accounts_profile_chrome

            kill_all_accounts_profile_chrome(cleanup_artifacts=False)
        except Exception:
            pass
