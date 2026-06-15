"""Логи дашборда: консоль всегда, файловая ротация по DASHBOARD_LOG_*."""
from __future__ import annotations

import os
from pathlib import Path


def _file_logging_enabled() -> bool:
    raw_enabled = os.getenv("DASHBOARD_FILE_LOG", "").strip().lower()
    if raw_enabled in ("0", "false", "no", "off"):
        return False
    if raw_enabled == "":
        run_sched = os.getenv("RUN_SCHEDULER", "").strip().lower() in (
            "1",
            "true",
            "yes",
            "on",
        )
        return run_sched
    return True


def build_logging(*, base_dir: Path) -> dict:
    """
    LOGGING для settings.py.
    Консоль — всегда; файл backend/var/log/backend.log — по DASHBOARD_FILE_LOG.
  """
    try:
        retention = max(1, min(90, int(os.getenv("DASHBOARD_LOG_RETENTION_DAYS", "7") or "7")))
    except ValueError:
        retention = 7

    handlers: dict = {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "dashboard_verbose",
            "filters": ["suppress_noisy_polling"],
        },
    }
    root_handlers = ["console"]
    app_handlers = ["console"]

    if _file_logging_enabled():
        log_dir = Path(os.getenv("DASHBOARD_LOG_DIR", str(base_dir / "var" / "log"))).expanduser()
        log_dir.mkdir(parents=True, exist_ok=True)
        handlers["dashboard_file"] = {
            "class": "logging.handlers.TimedRotatingFileHandler",
            "filename": str(log_dir / "backend.log"),
            "when": "midnight",
            "interval": 1,
            "backupCount": retention,
            "encoding": "utf-8",
            "formatter": "dashboard_verbose",
            "filters": ["suppress_noisy_polling"],
        }
        root_handlers.append("dashboard_file")
        app_handlers.append("dashboard_file")

    return {
        "version": 1,
        "disable_existing_loggers": False,
        "filters": {
            "suppress_noisy_polling": {
                "()": "config.http_log_filters.SuppressNoisyPollingFilter",
            },
        },
        "formatters": {
            "dashboard_verbose": {
                "format": "%(asctime)s %(levelname)s [%(name)s] %(message)s",
                "datefmt": "%Y-%m-%d %H:%M:%S",
            },
        },
        "handlers": handlers,
        "root": {
            "handlers": root_handlers,
            "level": os.getenv("DASHBOARD_LOG_LEVEL", "INFO").upper(),
        },
        "loggers": {
            "django": {
                "handlers": app_handlers,
                "level": "INFO",
                "propagate": False,
            },
            "django.request": {
                "handlers": app_handlers,
                "level": "WARNING",
                "propagate": False,
            },
            "django.server": {
                "handlers": app_handlers,
                "level": "INFO",
                "propagate": False,
            },
            "accounts": {
                "handlers": app_handlers,
                "level": "INFO",
                "propagate": False,
            },
            "platforms": {
                "handlers": app_handlers,
                "level": "INFO",
                "propagate": False,
            },
            "apscheduler": {
                "handlers": app_handlers,
                "level": "INFO",
                "propagate": False,
            },
        },
    }


def build_file_logging(*, base_dir: Path) -> dict | None:
    """Обратная совместимость: None если файловые логи выключены."""
    if not _file_logging_enabled():
        return None
    return build_logging(base_dir=base_dir)
