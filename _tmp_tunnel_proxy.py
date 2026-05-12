from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError


FRONTEND = "http://127.0.0.1:5173"
BACKEND = "http://127.0.0.1:8000"
LISTEN = ("127.0.0.1", 5190)


class ProxyHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _target_base(self):
        path = self.path or "/"
        if path.startswith("/api/") or path.startswith("/admin/") or path.startswith("/healthz"):
            return BACKEND
        return FRONTEND

    def _forward(self):
        target = f"{self._target_base()}{self.path}"
        length = int(self.headers.get("Content-Length", "0") or "0")
        body = self.rfile.read(length) if length > 0 else None

        headers = {}
        for k, v in self.headers.items():
            lk = k.lower()
            if lk in {"host", "connection", "content-length"}:
                continue
            headers[k] = v

        req = Request(target, data=body, method=self.command, headers=headers)
        try:
            with urlopen(req, timeout=60) as resp:
                data = resp.read()
                self.send_response(resp.status)
                for k, v in resp.headers.items():
                    lk = k.lower()
                    if lk in {"transfer-encoding", "connection", "content-encoding"}:
                        continue
                    if lk == "content-length":
                        continue
                    self.send_header(k, v)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
        except HTTPError as e:
            data = e.read() if hasattr(e, "read") else b""
            self.send_response(e.code)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            if data:
                self.wfile.write(data)
        except URLError as e:
            msg = f"Proxy upstream error: {e}".encode("utf-8")
            self.send_response(502)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(msg)))
            self.end_headers()
            self.wfile.write(msg)

    def do_GET(self):
        self._forward()

    def do_POST(self):
        self._forward()

    def do_PATCH(self):
        self._forward()

    def do_DELETE(self):
        self._forward()

    def do_PUT(self):
        self._forward()

    def do_OPTIONS(self):
        self._forward()


if __name__ == "__main__":
    server = ThreadingHTTPServer(LISTEN, ProxyHandler)
    print(f"proxy listening on http://{LISTEN[0]}:{LISTEN[1]}")
    server.serve_forever()
