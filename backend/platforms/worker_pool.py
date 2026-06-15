import atexit
import json
import os
import queue
import subprocess
import sys
import threading
import time
from pathlib import Path

_REFRESH_FORCE_STOP = threading.Event()


def mark_playwright_refresh_force_stop() -> None:
    """Сразу после «Остановить» — не поднимать новые демоны до сброса флага."""
    _REFRESH_FORCE_STOP.set()


def clear_playwright_refresh_force_stop() -> None:
    _REFRESH_FORCE_STOP.clear()


def refresh_stop_requested() -> bool:
    if _REFRESH_FORCE_STOP.is_set():
        return True
    try:
        from accounts.warm_run_detail import is_refresh_cancel_requested

        return bool(is_refresh_cancel_requested())
    except Exception:
        return False


def _abort_if_refresh_stop() -> None:
    if refresh_stop_requested():
        from accounts.refresh_cancel import RefreshCancelledError

        raise RefreshCancelledError("Остановлено пользователем")


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


def sync_accounts_browser_env() -> dict[str, str]:
    """
    Проставить BROWSER_PROFILE_DIR / BROWSER_HEADLESS из ACCOUNTS_BROWSER_* Django
    в os.environ текущего процесса (manage.py warm_tiktok_session, shell и т.п.).
    """
    applied: dict[str, str] = {}
    try:
        from django.conf import settings as dj_settings
    except Exception:
        return applied

    prof = getattr(dj_settings, "ACCOUNTS_BROWSER_PROFILE_DIR", None)
    if prof is not None:
        p = Path(prof)
        p.mkdir(parents=True, exist_ok=True)
        s = str(p)
        os.environ["BROWSER_PROFILE_DIR"] = s
        applied["BROWSER_PROFILE_DIR"] = s
    hl = getattr(dj_settings, "ACCOUNTS_BROWSER_HEADLESS", None)
    if hl is not None:
        s = "true" if hl else "false"
        os.environ["BROWSER_HEADLESS"] = s
        applied["BROWSER_HEADLESS"] = s
    try:
        from platforms.tiktok.sadcaptcha import sync_sadcaptcha_env

        applied.update(sync_sadcaptcha_env())
    except Exception:
        pass
    return applied


def _compose_worker_env(backend_root: str) -> dict:
    """
    Env дочернего воркера: каталог профиля / headless как у дашборда (AccountsStats,
    refresh, съём аудитории) — см. ACCOUNTS_BROWSER_* в settings, задаются через
    backend/config/worker_accounts.env.
    """
    env = _worker_subprocess_env(backend_root)
    sync_accounts_browser_env()
    for key in (
        "BROWSER_PROFILE_DIR",
        "BROWSER_HEADLESS",
        "SADCAPTCHA_API_KEY",
        "SADCAPTCHA_ENABLED",
        "SADCAPTCHA_SOLVE_RETRIES",
        "SADCAPTCHA_DETECT_TIMEOUT_SEC",
    ):
        if key in os.environ:
            env[key] = os.environ[key]
    threads_nav = (os.environ.get("THREADS_NAV_TIMEOUT_MS") or "").strip()
    if not threads_nav:
        threads_nav = "60000"
    env["THREADS_NAV_TIMEOUT_MS"] = threads_nav
    for threads_key in (
        "THREADS_POST_VIEWS_MAX_POSTS",
        "THREADS_HUMAN_BATCH_MAX_ROUNDS",
        "THREADS_HUMAN_BATCH_SIZE",
    ):
        val = (os.environ.get(threads_key) or "").strip()
        if val:
            env[threads_key] = val
    auth_nav = (os.environ.get("AUTH_NAV_TIMEOUT_MS") or "").strip()
    if auth_nav:
        env["AUTH_NAV_TIMEOUT_MS"] = auth_nav
    try:
        from platforms.worker_utils import normalize_playwright_browsers_env

        pw_path = normalize_playwright_browsers_env(env)
        if pw_path:
            print(
                f"[worker_pool] PLAYWRIGHT_BROWSERS_PATH={pw_path}",
                file=sys.stderr,
                flush=True,
            )
    except Exception:
        pass
    return env


def pool_storage_key(worker_path: Path) -> str:
    return str(worker_path.resolve())


def _kill_chromium_after_worker(chrome_roots: list[Path] | None = None) -> None:
    """
    None — снять Chrome по всем каталогам профиля (refresh stop, полный shutdown).
    list — только указанные user-data-dir (прогрев TikTok, один воркер).
    """
    try:
        from platforms.worker_utils import (
            kill_all_accounts_profile_chrome,
            kill_chrome_profile_roots,
        )

        if chrome_roots:
            kill_chrome_profile_roots(chrome_roots, cleanup_artifacts=False)
        else:
            kill_all_accounts_profile_chrome(cleanup_artifacts=False)
    except Exception:
        pass


def _worker_daemon_ready_timeout_sec() -> float:
    raw = (os.environ.get("WORKER_DAEMON_READY_TIMEOUT_SEC") or "120").strip()
    try:
        return max(30.0, min(600.0, float(raw)))
    except ValueError:
        return 120.0


class _WorkerHandle:
    def __init__(
        self,
        worker_path: Path,
        *,
        chrome_roots_on_close: list[Path] | None = None,
    ):
        self.worker_path = worker_path
        self._chrome_roots_on_close = chrome_roots_on_close
        self.lock = threading.Lock()
        self._browser_ready = threading.Event()
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
                if (
                    "_worker] launch_context" in line
                    or "[tiktok_worker] launch_context" in line
                    or "[tiktok_worker] slot=" in line
                ):
                    self._browser_ready.set()

    def wait_until_browser_ready(self, *, timeout_sec: float | None = None) -> None:
        """Дождаться launch_context в демоне (иначе stdin-запрос зависнет до открытия Chrome)."""
        if self._browser_ready.is_set():
            return
        limit = float(timeout_sec if timeout_sec is not None else _worker_daemon_ready_timeout_sec())
        deadline = time.monotonic() + limit
        while time.monotonic() < deadline:
            if self.proc.poll() is not None:
                raise ValueError(
                    "Фоновый worker завершился при запуске браузера. "
                    "Закройте зависший Chrome (профиль TikStatsChromeProfile) и повторите."
                )
            if self._browser_ready.is_set():
                return
            time.sleep(0.2)
        raise ValueError(
            f"Таймаут запуска браузера ({int(limit)} с). "
            "Закройте Chrome с профилем TikStatsChromeProfile (Диспетчер задач) и повторите."
        )

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

        # Пока worker крутит браузер, не держим idle-соединение к Postgres в этом потоке.
        try:
            from accounts.db_connections import release_db_for_long_task

            release_db_for_long_task()
        except Exception:
            pass

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
        try:
            from accounts.db_connections import ensure_fresh_db_connections

            ensure_fresh_db_connections()
        except Exception:
            pass
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
        _kill_chromium_after_worker(self._chrome_roots_on_close)


def _dashboard_backend_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _pool_tracked_pids() -> set[int]:
    keep: set[int] = set()
    with _GLOBAL_LOCK:
        for handle in _HANDLES.values():
            proc = getattr(handle, "proc", None)
            if proc is not None and proc.poll() is None:
                keep.add(int(proc.pid))
    return keep


def reconcile_orphan_worker_daemons(worker_path: Path | None = None) -> int:
    """
    Снять лишние ``worker.py --daemon`` этого backend (после autoreload / сбоя пула).

    Оставляет только PID, уже зарегистрированные в ``_HANDLES``.
    """
    from platforms.worker_utils import (
        find_dashboard_worker_daemon_pids,
        kill_worker_process_pids,
        live_dashboard_runserver_pids,
        pid_is_descendant_of,
    )

    backend_root = (
        _backend_dir_for_worker(worker_path)
        if worker_path is not None
        else _dashboard_backend_root()
    )
    keep = _pool_tracked_pids()
    live_servers = live_dashboard_runserver_pids(backend_root)
    orphans: list[int] = []
    for pid in find_dashboard_worker_daemon_pids(
        backend_root,
        worker_script=worker_path.resolve() if worker_path is not None else None,
    ):
        if pid in keep:
            continue
        # Воркер другого (или этого) runserver — не «зомби» для чужого процесса Django.
        if any(pid_is_descendant_of(pid, srv) for srv in live_servers):
            continue
        orphans.append(pid)
    if not orphans:
        return 0
    killed = kill_worker_process_pids(orphans)
    if killed:
        label = worker_path.name if worker_path is not None else "all"
        print(
            f"[worker_pool] снято зомби-воркеров ({label}): {killed}",
            file=sys.stderr,
            flush=True,
        )
        roots = _chrome_roots_for_worker(worker_path) if worker_path is not None else None
        _kill_chromium_after_worker(roots)
        time.sleep(0.35)
    return killed


def _chrome_roots_for_worker(worker_path: Path) -> list[Path] | None:
    """Каталоги Chrome только для этой платформы; None = все профили дашборда."""
    name = worker_path.resolve().parent.name
    if name == "tiktok":
        from platforms.tiktok.browser_profile import (
            REFRESH_BROWSER_AUTHORIZED,
            REFRESH_BROWSER_SECONDARY,
            profile_base_dir,
            user_data_dir_for_slot,
        )

        base = profile_base_dir()
        return [
            user_data_dir_for_slot(base, REFRESH_BROWSER_AUTHORIZED),
            user_data_dir_for_slot(base, REFRESH_BROWSER_SECONDARY),
        ]
    if name == "facebook":
        from platforms.worker_utils import accounts_profile_roots

        base = accounts_profile_roots()[0]
        roots = [base, base / "facebook_persistent", base / "facebook_from_state"]
        return [p for p in roots if p.is_dir() or not p.exists()]
    return None


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
        "таймаут запуска браузера",
    )
    return any(m in msg for m in markers)


def _prepare_worker_spawn(worker_path: Path) -> None:
    """Освободить профиль Chrome и снять зомби-воркеры перед новым демоном."""
    _abort_if_refresh_stop()
    _kill_chromium_after_worker(_chrome_roots_for_worker(worker_path))
    time.sleep(0.45)
    reconcile_orphan_worker_daemons(worker_path)


def release_worker(worker_path: Path) -> None:
    """Снять демон из пула (перед subs one-shot TikTok, чтобы не держать тот же Chrome)."""
    shutdown_worker(worker_path)


def call_worker_oneshot(
    worker_path: Path,
    payload: dict,
    *,
    timeout_sec: float | None = 3600.0,
    extra_env: dict[str, str] | None = None,
) -> dict:
    """
    Один процесс worker.py <json> без демона — для клиента subs (TikTok enrich с окном).
    AccountsStats по-прежнему использует call_worker / ensure_worker.
    """
    backend_root = str(_backend_dir_for_worker(worker_path))
    env = _compose_worker_env(backend_root)
    if extra_env:
        env.update(extra_env)
    cmd = [sys.executable, str(worker_path.resolve()), json.dumps(payload, ensure_ascii=False)]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_sec,
            cwd=backend_root,
            env=env,
        )
    except subprocess.TimeoutExpired as exc:
        raise ValueError(
            f"Таймаут one-shot worker ({int(timeout_sec or 0)}с). Попробуйте ещё раз."
        ) from exc
    if proc.stderr:
        for line in proc.stderr.splitlines():
            if line.strip():
                print(line, file=sys.stderr)
    if proc.returncode not in (0, None) and not (proc.stdout or "").strip():
        raise ValueError(
            f"Worker завершился с кодом {proc.returncode}: "
            f"{(proc.stderr or proc.stdout or '')[:500]}"
        )
    lines = [ln for ln in (proc.stdout or "").splitlines() if ln.strip()]
    if not lines:
        raise ValueError("Worker не вернул ответ (пустой stdout)")
    try:
        data = json.loads(lines[-1].strip())
    except Exception as exc:
        raise ValueError("Ошибка парсинга ответа worker") from exc
    if isinstance(data, dict) and "error" in data:
        raise ValueError(data["error"])
    return data


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
    if worker_path.resolve().parent.name == "rumble":
        try:
            from platforms.rumble.scraper import skip_playwright_prewarm

            if skip_playwright_prewarm():
                raise ValueError(
                    "Rumble Playwright отключён — используется FlareSolverr. "
                    "Для окна браузера: RUMBLE_PLAYWRIGHT_FALLBACK=1."
                )
        except ValueError:
            raise
        except Exception:
            pass

    key = pool_storage_key(worker_path)
    last_exc: BaseException | None = None
    for _attempt in range(3):
        _abort_if_refresh_stop()
        spawned = False
        handle = None
        need_prepare = False
        with _GLOBAL_LOCK:
            handle = _HANDLES.get(key)
            dead = handle is None or handle.proc.poll() is not None
            if dead:
                if handle is not None:
                    try:
                        handle.close()
                    except Exception:
                        pass
                    _HANDLES.pop(key, None)
                need_prepare = True
        if need_prepare:
            # Не держим GLOBAL_LOCK во время kill Chrome / reconcile — иначе
            # параллельные платформы «зависают» на съёме без окон.
            _prepare_worker_spawn(worker_path)
            with _GLOBAL_LOCK:
                handle = _HANDLES.get(key)
                if handle is None or handle.proc.poll() is not None:
                    roots = _chrome_roots_for_worker(worker_path)
                    handle = _WorkerHandle(worker_path, chrome_roots_on_close=roots)
                    _HANDLES[key] = handle
                    spawned = True
                else:
                    handle = _HANDLES.get(key)
        if handle is None:
            raise ValueError("Worker недоступен")
        if spawned or not handle._browser_ready.is_set():
            handle.wait_until_browser_ready()
        try:
            return handle.call(payload, timeout_sec=timeout_sec)
        except Exception as exc:
            last_exc = exc
            if refresh_stop_requested():
                from accounts.refresh_cancel import RefreshCancelledError

                raise RefreshCancelledError("Остановлено пользователем") from exc
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
                _kill_chromium_after_worker(_chrome_roots_for_worker(worker_path))
                time.sleep(0.85)
    assert last_exc is not None
    raise last_exc


def _spawn_worker_daemon(worker_path: Path, *, reconcile: bool = True) -> None:
    """Поднять один демон в пуле (без глобального kill_all после старта)."""
    if refresh_stop_requested():
        return
    key = pool_storage_key(worker_path)
    need_spawn = False
    with _GLOBAL_LOCK:
        handle = _HANDLES.get(key)
        if handle is None or handle.proc.poll() is not None:
            if handle is not None:
                try:
                    handle.close()
                except Exception:
                    pass
            need_spawn = True
    if not need_spawn:
        return
    if reconcile:
        _prepare_worker_spawn(worker_path)
    else:
        _kill_chromium_after_worker(_chrome_roots_for_worker(worker_path))
        time.sleep(0.45)
    with _GLOBAL_LOCK:
        handle = _HANDLES.get(key)
        if handle is None or handle.proc.poll() is not None:
            roots = _chrome_roots_for_worker(worker_path)
            _HANDLES[key] = _WorkerHandle(
                worker_path,
                chrome_roots_on_close=roots,
            )
    time.sleep(0.5)


def ensure_worker(worker_path: Path) -> None:
    """
    Ensure daemon worker process is started and kept in pool.
    Used for pre-warming browser windows/contexts before bulk refresh.

    Не вызываем kill_all_accounts_profile_chrome после spawn: демон уже открыл
    Chromium (persistent / TikTok user-data-dir), а kill снимает только процессы
    с путём общего профиля — окна на storage_state (Instagram/X/Threads) не трогает,
    из‑за чего при автообновлении «остаются» только они.
    См. prewarm_workers и handle.close / call_worker retry.
    """
    _spawn_worker_daemon(worker_path)


def prewarm_workers(
    worker_paths: list[Path],
    *,
    wait_browser_ready: bool = False,
) -> None:
    """
    Поднять несколько Playwright-демонов подряд.

    Не вызывает kill_all_accounts_profile_chrome между платформами — иначе
    при refresh_all/автообновлении остаются только окна на storage_state
    (Instagram/X/Threads), а TikTok/Facebook в общем профиле гасятся.
    """
    paths = [p for p in worker_paths if p.exists()]
    try:
        from platforms.rumble.scraper import skip_playwright_prewarm

        if skip_playwright_prewarm():
            paths = [p for p in paths if p.resolve().parent.name != "rumble"]
    except Exception:
        pass
    if not paths:
        return
    reconcile_orphan_worker_daemons()
    stagger = float((os.environ.get("ACCOUNTS_PREWARM_STAGGER_SEC") or "1.5").strip() or "1.5")
    stagger = max(0.5, min(8.0, stagger))
    ready_timeout = _worker_daemon_ready_timeout_sec()
    if wait_browser_ready:
        raw = (os.environ.get("ACCOUNTS_PREWARM_READY_TIMEOUT_SEC") or "").strip()
        if raw:
            try:
                ready_timeout = max(60.0, min(600.0, float(raw)))
            except ValueError:
                pass
    for worker_path in paths:
        _spawn_worker_daemon(worker_path, reconcile=False)
        if wait_browser_ready:
            plat = worker_path.resolve().parent.name
            with _GLOBAL_LOCK:
                handle = _HANDLES.get(pool_storage_key(worker_path))
            if handle is not None:
                try:
                    handle.wait_until_browser_ready(timeout_sec=ready_timeout)
                    print(
                        f"[worker_pool] prewarm {plat}: браузер готов",
                        file=sys.stderr,
                        flush=True,
                    )
                except Exception as exc:
                    print(
                        f"[worker_pool] prewarm {plat}: {exc}",
                        file=sys.stderr,
                        flush=True,
                    )
        time.sleep(stagger)


@atexit.register
def _shutdown_workers() -> None:
    """При выходе Python закрыть дочерние worker-процессы. Обход: PLAYWRIGHT_POOL_SKIP_ATEXIT=1."""
    if os.getenv("PLAYWRIGHT_POOL_SKIP_ATEXIT", "").strip().lower() in {"1", "true", "yes", "on"}:
        return
    for h in list(_HANDLES.values()):
        h.close()


def shutdown_all_workers() -> None:
    """Закрыть все демоны Playwright — после сброса сессии в настройках."""
    mark_playwright_refresh_force_stop()
    with _GLOBAL_LOCK:
        for h in list(_HANDLES.values()):
            try:
                h.close()
            except Exception:
                pass
        _HANDLES.clear()
    reconcile_orphan_worker_daemons()
    _kill_chromium_after_worker(None)


def shutdown_worker(worker_path: Path) -> bool:
    """Закрыть один демон Playwright; Chrome — только каталоги этой платформы."""
    key = pool_storage_key(worker_path)
    handle = None
    with _GLOBAL_LOCK:
        handle = _HANDLES.pop(key, None)
    if handle is None:
        reconcile_orphan_worker_daemons(worker_path)
        return False
    try:
        handle.close()
    except Exception:
        pass
    return True


def worker_daemon_alive(worker_path: Path) -> bool:
    """True, если демон worker.py для этого пути уже в пуле и процесс жив."""
    key = pool_storage_key(worker_path)
    with _GLOBAL_LOCK:
        handle = _HANDLES.get(key)
        if handle is None:
            return False
        proc = getattr(handle, "proc", None)
        return proc is not None and proc.poll() is None


def prepare_tiktok_warm_session() -> None:
    """Перед warm_tiktok_session: только TikTok worker/Chrome, не Facebook и не весь пул."""
    worker_path = Path(__file__).resolve().parent / "tiktok" / "worker.py"
    if worker_path.exists():
        shutdown_worker(worker_path)
    reconcile_orphan_worker_daemons(worker_path if worker_path.exists() else None)


def prepare_facebook_warm_session() -> None:
    """Перед warm_facebook_session: только Facebook worker/Chrome, не TikTok и не весь пул."""
    worker_path = Path(__file__).resolve().parent / "facebook" / "worker.py"
    if worker_path.exists():
        shutdown_worker(worker_path)
    reconcile_orphan_worker_daemons(worker_path if worker_path.exists() else None)


def shutdown_playwright_pool_aggressive(*, sleep_sec: float = 0.55) -> None:
    """
    Закрыть пул демонов и снять все Chromium профиля AccountsStats.
    Двойной проход kill нужен на Windows: после terminate() воркера дочерний Chrome
    часто остаётся в доке ещё сотни миллисекунд.
    """
    shutdown_all_workers()
    reconcile_orphan_worker_daemons()
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
