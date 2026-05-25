#!/usr/bin/env python3
"""Обновить блок accounts-stats в /opt/nginx-proxy.conf."""
from pathlib import Path

conf = Path("/opt/nginx-proxy.conf")
fragment = Path("/tmp/nginx-accounts-stats.conf")
text = conf.read_text(encoding="utf-8")
block = fragment.read_text(encoding="utf-8").strip()

start = text.find("    set $dashboard_web http://dashboard-frontend:80;")
end = text.find("    # ── Block scanners and known probe paths")
if start < 0 or end < 0 or end <= start:
    raise SystemExit(f"markers not found: start={start} end={end}")

new_text = text[:start] + block + "\n\n" + text[end:]
conf.write_text(new_text, encoding="utf-8")
print("patched", conf)
