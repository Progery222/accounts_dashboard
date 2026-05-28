#!/usr/bin/env python3
"""Генерация ~/dashboard/.env на GPU-сервере Mobile Farm. Запуск на сервере из корня репо."""
import secrets
from pathlib import Path

root = Path(__file__).resolve().parent
example_path = root / ".env.example"
if not example_path.exists():
    raise SystemExit(f"missing {example_path}")

example = example_path.read_text(encoding="utf-8")
secret = secrets.token_urlsafe(48)
db_pass = secrets.token_urlsafe(24)

host_ip = "10.20.87.230"
hostname = "by01-mobilefarmgpu"
http_port = "9080"
public_http = f"http://{host_ip}:{http_port}"

lines = []
for raw in example.splitlines():
    line = raw
    if line.startswith("SECRET_KEY="):
        line = f"SECRET_KEY={secret}"
    elif line.startswith("DEBUG="):
        line = "DEBUG=false"
    elif line.startswith("ALLOWED_HOSTS="):
        line = f"ALLOWED_HOSTS={host_ip},{hostname},localhost,127.0.0.1"
    elif line.startswith("CSRF_EXTRA_ORIGINS="):
        line = f"CSRF_EXTRA_ORIGINS={public_http},http://127.0.0.1:{http_port}"
    elif line.startswith("CORS_EXTRA_ORIGINS="):
        line = f"CORS_EXTRA_ORIGINS={public_http},http://127.0.0.1:{http_port}"
    elif line.startswith("DB_PASSWORD="):
        line = f"DB_PASSWORD={db_pass}"
    elif line.startswith("DB_HOST="):
        line = "DB_HOST=postgres"
    elif line.startswith("DB_SSL_REQUIRE="):
        line = "DB_SSL_REQUIRE=false"
    elif line.startswith("RUN_SCHEDULER="):
        line = "RUN_SCHEDULER=true"
    elif line.startswith("BROWSER_HEADLESS="):
        line = "BROWSER_HEADLESS=true"
    elif line.startswith("BROWSER_PROFILE_DIR="):
        line = "BROWSER_PROFILE_DIR=/app/.browser-profile"
    elif line.startswith("INSTAGRAM_USERNAME="):
        line = "INSTAGRAM_USERNAME="
    elif line.startswith("INSTAGRAM_PASSWORD="):
        line = "INSTAGRAM_PASSWORD="
    lines.append(line)

extra = [
    "",
    "# --- Mobile Farm GPU (сгенерировано при деплое) ---",
    f"DASHBOARD_HTTP_PORT={http_port}",
    f"DASHBOARD_PUBLIC_URL={public_http}",
]
out = "\n".join(lines) + "\n" + "\n".join(extra) + "\n"
env_path = root / ".env"
env_path.write_text(out, encoding="utf-8")
env_path.chmod(0o600)

wa = root / "backend/config/worker_accounts.env"
ex = root / "backend/config/worker_accounts.env.example"
if ex.exists() and not wa.exists():
    text = ex.read_text(encoding="utf-8") + "\nACCOUNTS_BROWSER_HEADLESS=true\n"
    wa.write_text(text, encoding="utf-8")
    wa.chmod(0o600)

print("OK")
print("PUBLIC_URL", public_http)
print("PORT", http_port)
