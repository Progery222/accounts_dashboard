"""Файловые логи дашборда с ротацией по дням (см. DASHBOARD_LOG_* в settings)."""
from __future__ import annotations

import os
from pathlib import Path


def build_file_logging(*, base_dir: Path) -> dict | None:
    """
    Вернуть фрагмент LOGGING для settings или None, если файловые логи выключены.
    """
    raw_enabled = os.getenv("DASHBOARD_FILE_LOG", "").strip().lower()
    if raw_enabled in ("0", "false", "no", "off"):
        return None
    if raw_enabled == "":
        run_sched = os.getenv("RUN_SCHEDULER", "").strip().lower() in ("1", "true", "yes", "on")
        if not run_sched:
            return None

    log_dir = Path(os.getenv("DASHBOARD_LOG_DIR", str(base_dir / "var" / "log"))).expanduser()
    try:
        retention = max(1, min(90, int(os.getenv("DASHBOARD_LOG_RETENTION_DAYS", "7") or "7")))
    except ValueError:
        retention = 7

    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "backend.log"

    file_handler = {
        "class": "logging.handlers.TimedRotatingFileHandler",
        "filename": str(log_path),
        "when": "midnight",
        "interval": 1,
        "backupCount": retention,
        "encoding": "utf-8",
        "formatter": "dashboard_verbose",
    }

    return {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "dashboard_verbose": {
                "format": "%(asctime)s %(levelname)s [%(name)s] %(message)s",
                "datefmt": "%Y-%m-%d %H:%M:%S",
            },
        },
        "handlers": {
            "dashboard_file": file_handler,
            "console": {
                "class": "logging.StreamHandler",
                "formatter": "dashboard_verbose",
            },
        },
        "root": {
            "handlers": ["console", "dashboard_file"],
            "level": os.getenv("DASHBOARD_LOG_LEVEL", "INFO").upper(),
        },
        "loggers": {
            "django": {"handlers": ["console", "dashboard_file"], "level": "INFO", "propagate": False},
            "django.request": {"handlers": ["console", "dashboard_file"], "level": "WARNING", "propagate": False},
            "accounts": {"handlers": ["console", "dashboard_file"], "level": "INFO", "propagate": False},
            "platforms": {"handlers": ["console", "dashboard_file"], "level": "INFO", "propagate": False},
            "apscheduler": {"handlers": ["console", "dashboard_file"], "level": "INFO", "propagate": False},
        },
    }
