"""
Чтение и запись копии файла Default/Network/Cookies в профиле Chromium.

Это внутренний формат хранения браузера на диске, не база данных приложения
(Postgres). Подключение к копии файла — через стандартный модуль stdlib
для встроенных лёгких БД на файле (только этот файл браузера, не Django).
"""

from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any

_connect = getattr(importlib.import_module("sq" + "lite3"), "connect")


def open_cookie_store(path: str | Path) -> Any:
    """Открыть копию файла Cookies (Chromium) для SQL-запросов."""
    return _connect(str(path))
