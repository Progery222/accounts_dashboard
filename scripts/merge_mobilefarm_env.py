#!/usr/bin/env python3
"""Слить секреты из локального .env в серверный, сохранив хосты/CSRF/БД Mobile Farm."""
from __future__ import annotations

import argparse
import re
from pathlib import Path

# Не перезаписывать с локали — на сервере свои значения.
KEEP_SERVER = frozenset(
    {
        "SECRET_KEY",
        "DEBUG",
        "ALLOWED_HOSTS",
        "CSRF_EXTRA_ORIGINS",
        "CORS_EXTRA_ORIGINS",
        "DB_NAME",
        "DB_USER",
        "DB_PASSWORD",
        "DB_HOST",
        "DB_PORT",
        "DB_SSL_REQUIRE",
        "DATABASE_URL",
        "DASHBOARD_HTTP_PORT",
        "DASHBOARD_PUBLIC_URL",
        "BROWSER_PROFILE_DIR",
        "BROWSER_HEADLESS",
        "RUN_SCHEDULER",
    }
)

# Скопировать с локали, если задано (пустые локальные — не затирать сервер).
COPY_IF_SET = frozenset(
    {
        "YOUTUBE_API_KEY",
        "INSTAGRAM_USERNAME",
        "INSTAGRAM_PASSWORD",
        "INSTAGRAM_SESSION_FILE",
        "TELEGRAM_API_ID",
        "TELEGRAM_API_HASH",
        "TELEGRAM_PHONE",
        "TELEGRAM_SESSION_FILE",
        "FACEBOOK_EMAIL",
        "FACEBOOK_PASSWORD",
        "TIKTOK_USERNAME",
        "TIKTOK_PASSWORD",
        "TIKTOK_AUTH_AUTOFILL",
        "LINKS_API_URL",
        "LINKS_API_TOKEN",
        "LINKS_API_TIMEOUT",
        "APIFY_TOKEN",
        "APIFY_ENABLED",
        "APIFY_MAX_CONCURRENT_RUNS",
        "APIFY_POLL_INTERVAL_SEC",
        "APIFY_POLL_MAX_WAIT_SEC",
        "APIFY_WEBHOOK_SECRET",
        "APIFY_WEBHOOK_BASE_URL",
        "RAILWAY_FRONTEND_PUBLIC_DOMAIN",
        "DJANGO_USE_TLS_PROXY_HEADERS",
    }
)


def parse_env(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        m = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)=(.*)$", s)
        if m:
            out[m.group(1)] = m.group(2)
    return out


def render_env(order_lines: list[str], values: dict[str, str]) -> str:
    seen: set[str] = set()
    lines: list[str] = []
    for raw in order_lines:
        s = raw.strip()
        if not s or s.startswith("#"):
            lines.append(raw)
            continue
        m = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)=", s)
        if not m:
            lines.append(raw)
            continue
        key = m.group(1)
        seen.add(key)
        if key in values:
            lines.append(f"{key}={values[key]}")
        else:
            lines.append(raw)
    for key, val in sorted(values.items()):
        if key not in seen:
            lines.append(f"{key}={val}")
    return "\n".join(lines) + "\n"


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--local", type=Path, required=True, help="Локальный .env")
    p.add_argument("--server", type=Path, required=True, help="Текущий ~/dashboard/.env на сервере")
    p.add_argument("--out", type=Path, required=True, help="Куда записать результат")
    args = p.parse_args()

    local = parse_env(args.local.read_text(encoding="utf-8"))
    server = parse_env(args.server.read_text(encoding="utf-8"))
    merged = dict(server)

    for key in COPY_IF_SET:
        val = local.get(key, "")
        if val and val not in ("changeme", "your_ig_login", "your_tiktok_login"):
            merged[key] = val

    for key, val in server.items():
        if key in KEEP_SERVER:
            merged[key] = val

    order = args.server.read_text(encoding="utf-8").splitlines()
    args.out.write_text(render_env(order, merged), encoding="utf-8")
    args.out.chmod(0o600)
    print("OK", args.out)


if __name__ == "__main__":
    main()
