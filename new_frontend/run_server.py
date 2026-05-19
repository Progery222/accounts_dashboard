#!/usr/bin/env python3
"""
Статика new_frontend (AccountsStats / Atomic) на 127.0.0.1 (по умолчанию 5174).
Порт: NEW_FRONTEND_PORT — не используйте 5180: он зарезервирован под Vite «Подписчики» (../subs/frontend).
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
PORT = int(os.environ.get("NEW_FRONTEND_PORT", "5174") or "5174")
ROOT = Path(__file__).resolve().parent


def main() -> None:
    if PORT == 5180:
        print(
            "Порт 5180 зарезервирован под приложение «Подписчики» (Vite: ../subs/frontend, npm run dev).\n"
            "Остановите Atomic на 5180 и запустите subs. Для Atomic на другом порту, например:\n"
            "  set NEW_FRONTEND_PORT=5175\n"
            "  python run_server.py",
            file=sys.stderr,
        )
        sys.exit(1)
    if not (ROOT / "app.html").is_file():
        print("Ошибка: рядом с run_server.py должен лежать app.html (каталог new_frontend).", file=sys.stderr)
        sys.exit(1)
    os.chdir(ROOT)
    handler = http.server.SimpleHTTPRequestHandler
    with socketserver.TCPServer((HOST, PORT), handler) as httpd:
        print(f"new_frontend: http://{HOST}:{PORT}/  (корень {ROOT})")
        print("Это Atomic (app.html), не Vite ../frontend (5173).")
        print(
            "Этот сервер не проксирует /api/ (POST сюда -> HTTP 501); "
            "через туннель см. ingress в cloudflared.5174.yml; стек Subs — см. ../subs/frontend (API subs :8010, dashboard :8000)."
        )
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nОстановлено.")


if __name__ == "__main__":
    main()
