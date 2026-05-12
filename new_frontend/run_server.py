#!/usr/bin/env python3
"""
Статика new_frontend на 127.0.0.1:5174.
Корень всегда каталог этого файла — не зависит от текущей рабочей директории.
(Основной Vite-фронт в ../frontend — порт 5173.)
"""
from __future__ import annotations

import http.server
import os
import socketserver
import sys
from pathlib import Path

HOST = "127.0.0.1"
PORT = 5174
ROOT = Path(__file__).resolve().parent


def main() -> None:
    if not (ROOT / "app.html").is_file():
        print("Ошибка: рядом с run_server.py должен лежать app.html (каталог new_frontend).", file=sys.stderr)
        sys.exit(1)
    os.chdir(ROOT)
    handler = http.server.SimpleHTTPRequestHandler
    with socketserver.TCPServer((HOST, PORT), handler) as httpd:
        print(f"new_frontend: http://{HOST}:{PORT}/  (корень {ROOT})")
        print("Это Atomic (app.html), не Vite ../frontend (5173).")
        print("API: Django на http://127.0.0.1:8000 — этот сервер не проксирует /api/ (POST сюда -> HTTP 501).")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nОстановлено.")


if __name__ == "__main__":
    main()
