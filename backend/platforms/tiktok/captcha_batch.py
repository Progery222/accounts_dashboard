"""TikTok: зависание на капче — остальные TikTok в батче быстро завершаются с ошибкой."""

from __future__ import annotations

import threading
from pathlib import Path

TIKTOK_CAPTCHA_STALL_DEFAULT = (
    "TikTok: капча не пройдена за отведённое время (≈5 мин) — "
    "остальные аккаунты TikTok в очереди не обновлялись"
)

_CAPTCHA_STALL_MARKERS = (
    "время ожидания капчи истекло",
    "sadcaptcha не снял капчу",
    "не снял капчу за отведённое время",
    "tiktok: sadcaptcha",
)

_TT_WORKER = Path(__file__).parent / "worker.py"


def is_tiktok_captcha_stall_error(exc: BaseException) -> bool:
    msg = str(exc).lower()
    if "tiktok" not in msg and "капч" not in msg:
        return False
    return any(m in msg for m in _CAPTCHA_STALL_MARKERS)


def shutdown_tiktok_worker() -> bool:
    try:
        from platforms.worker_pool import shutdown_worker

        return shutdown_worker(_TT_WORKER)
    except Exception:
        return False


class TikTokRefreshBatchGuard:
    """После таймаута капчи на одном TikTok — остальные в батче сразу «ошибка»."""

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
            raw = (message or "").strip()
            self._tripped = True
            self._reason = raw or TIKTOK_CAPTCHA_STALL_DEFAULT

    def error_detail(self) -> str:
        r = self.reason()
        return r or TIKTOK_CAPTCHA_STALL_DEFAULT


def on_tiktok_refresh_error(
    platform: str,
    exc: BaseException,
    guard: TikTokRefreshBatchGuard | None,
) -> None:
    if guard is None or (platform or "").strip().lower() != "tiktok":
        return
    if not is_tiktok_captcha_stall_error(exc):
        return
    shutdown_tiktok_worker()
    guard.trip(str(exc))
