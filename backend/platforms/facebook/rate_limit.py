"""Facebook rate limit / «Вы временно заблокированы» — детекция и остановка батча refresh."""

from __future__ import annotations

import threading
from pathlib import Path

FACEBOOK_RATE_LIMIT_PREFIX = "Facebook временно ограничил доступ"

_RATE_LIMIT_MARKERS = (
    "facebook временно ограничил",
    "временно заблокирован",
    "temporarily blocked",
    "слишком часто использовали",
    "using this feature too often",
    "we temporarily blocked",
    "you're temporarily blocked",
    "you are temporarily blocked",
)

_FB_WORKER = Path(__file__).parent / "worker.py"


def is_facebook_rate_limited_error(exc: BaseException) -> bool:
    msg = str(exc).lower()
    return any(m in msg for m in _RATE_LIMIT_MARKERS)


def shutdown_facebook_worker() -> bool:
    """Закрыть демон Facebook и окно Chromium."""
    try:
        from platforms.worker_pool import shutdown_worker

        return shutdown_worker(_FB_WORKER)
    except Exception:
        return False


class FacebookRefreshBatchGuard:
    """После первого rate limit в батче — остальные FB в очереди пропускаются."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._tripped = False
        self._reason = ""

    def is_tripped(self) -> bool:
        with self._lock:
            return self._tripped

    def reason(self) -> str:
        with self._lock:
            return self._reason

    def trip(self, message: str = "") -> None:
        with self._lock:
            if self._tripped:
                return
            self._tripped = True
            self._reason = (message or "").strip() or (
                "Facebook временно заблокирован — пропуск до следующего автообновления"
            )

    def skip_detail(self) -> str:
        r = self.reason()
        return r or "Facebook временно заблокирован — пропуск оставшихся в очереди"
