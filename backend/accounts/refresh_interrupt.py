"""Прерывание длительного refresh / автообновления по запросу пользователя."""

from __future__ import annotations

import sys


def interrupt_refresh_playwright_workers(*, label: str = "refresh_stop") -> None:
    """
    После cancel_requested=True: закрыть демоны Playwright, чтобы call_worker
    не висел до таймаута (Instagram 180 с, TikTok navigation и т.д.).
    """
    try:
        from .refresh_all_warm import stop_facebook_parallel_warm

        stop_facebook_parallel_warm(label=label, progress_path=None)
    except Exception as exc:
        print(f"[{label}] stop facebook parallel warm: {exc}", file=sys.stderr, flush=True)

    try:
        from platforms.worker_pool import shutdown_all_workers

        shutdown_all_workers()
        print(f"[{label}] Playwright workers shutdown", file=sys.stderr, flush=True)
    except Exception as exc:
        print(f"[{label}] shutdown workers failed: {exc}", file=sys.stderr, flush=True)

    try:
        from accounts.models import ScrapeBackendChoice, ScrapeBackendConfig

        if ScrapeBackendConfig.get().facebook_backend != ScrapeBackendChoice.APIFY:
            from platforms.facebook.rate_limit import shutdown_facebook_worker

            shutdown_facebook_worker()
    except Exception:
        pass
