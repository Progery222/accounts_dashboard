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
from urllib.parse import urlparse

HOST = "127.0.0.1"
PORT = int(os.environ.get("NEW_FRONTEND_PORT", "5174") or "5174")
ROOT = Path(__file__).resolve().parent

# Явные SPA-маршруты (без расширения файла)
SPA_PATHS = frozenset({
    "/",
    "/settings",
    "/analytics",
    "/profiles",
    "/tv",
    "/emu",
    "/emu-settings",
    "/accounts",
})


class ThreadingHTTPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    daemon_threads = True
    allow_reuse_address = True


class AtomicHTTPRequestHandler(http.server.SimpleHTTPRequestHandler):
    """Статика с диска; остальные GET → app.html (SPA, в т.ч. /emu)."""

    def _url_path(self) -> str:
        return urlparse(self.path).path

    def _clean_path(self) -> str:
        return self._url_path().rstrip("/") or "/"

    def _local_file(self, url_path: str) -> Path | None:
        rel = url_path.lstrip("/")
        if not rel or rel.endswith("/"):
            return None
        candidate = (ROOT / rel.replace("/", os.sep)).resolve()
        try:
            candidate.relative_to(ROOT.resolve())
        except ValueError:
            return None
        return candidate if candidate.is_file() else None

    def _should_spa(self, clean: str) -> bool:
        if clean in SPA_PATHS:
            return True
        # /emu/, /settings/ и любые «человеческие» пути без расширения
        last = clean.rsplit("/", 1)[-1]
        return bool(last) and "." not in last

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        clean = parsed.path.rstrip("/") or "/"
        if self._local_file(parsed.path) is None and self._should_spa(clean):
            qs = f"?{parsed.query}" if parsed.query else ""
            self.path = f"/app.html{qs}"
        return super().do_GET()

    def end_headers(self) -> None:
        # app.html компилируется Babel в браузере — не кэшировать
        if self._url_path().endswith("app.html") or self._clean_path() in SPA_PATHS:
            self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
            self.send_header("Pragma", "no-cache")
        super().end_headers()


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
    try:
        httpd = ThreadingHTTPServer((HOST, PORT), AtomicHTTPRequestHandler)
    except OSError as exc:
        win_in_use = getattr(exc, "winerror", None) == 10048
        if exc.errno in (48, 98) or win_in_use or "address already in use" in str(exc).lower():
            print(
                f"Порт {PORT} уже занят (часто старый «python -m http.server» без SPA).\n"
                f"Остановите процесс на {PORT} или: set NEW_FRONTEND_PORT=5175 && python run_server.py",
                file=sys.stderr,
            )
            sys.exit(1)
        raise
    with httpd:
        print(f"new_frontend: http://{HOST}:{PORT}/  (корень {ROOT})")
        print(f"  TV emu: http://{HOST}:{PORT}/emu  |  настройки: http://{HOST}:{PORT}/emu-settings")
        print("  Запасной вход: http://{0}:{1}/app.html?route=emu".format(HOST, PORT))
        print("Это Atomic (run_server.py), не «python -m http.server» и не Vite ../frontend (5173).")
        print(
            "Этот сервер не проксирует /api/ (POST сюда -> HTTP 501); "
            "через туннель см. ingress в cloudflared.5174.yml; стек Subs — ../subs/frontend."
        )
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nОстановлено.")


if __name__ == "__main__":
    main()
