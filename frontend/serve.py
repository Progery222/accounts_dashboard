"""Статика фронтенда AccountsStats.

Отдаёт index.html на 127.0.0.1:5174 без кеша и с SPA-fallback.
Запросы к API не проксирует — фронтенд ходит напрямую на Django (:8010),
CORS при DEBUG=True разрешён на стороне бэкенда.

    python serve.py [порт]
"""

import os
import sys
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.abspath(__file__))
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 5174


class Handler(SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header("Cache-Control", "no-store, must-revalidate")
        self.send_header("Pragma", "no-cache")
        super().end_headers()

    def send_head(self):
        # Всё, что не файл на диске, отдаём как index.html — клиентский роутинг.
        path = self.translate_path(self.path)
        if not os.path.exists(path) or os.path.isdir(path):
            if not os.path.isdir(path) or not os.path.exists(os.path.join(path, "index.html")):
                self.path = "/index.html"
        return super().send_head()

    def log_message(self, fmt, *args):
        if "200" not in (args[1] if len(args) > 1 else ""):
            super().log_message(fmt, *args)


def main():
    handler = partial(Handler, directory=ROOT)
    with ThreadingHTTPServer(("127.0.0.1", PORT), handler) as srv:
        print(f"AccountsStats UI  →  http://127.0.0.1:{PORT}/")
        print(f"каталог: {ROOT}")
        try:
            srv.serve_forever()
        except KeyboardInterrupt:
            print("\nостановлено")


if __name__ == "__main__":
    main()
