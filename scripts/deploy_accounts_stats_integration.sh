#!/bin/bash
# Запуск на VPS от root: bash deploy_accounts_stats_integration.sh
set -euo pipefail

NGINX_CONF=/opt/nginx-proxy.conf
SNIPPET=/opt/dashboard/deploy/nginx-atome-accounts-stats.conf

if ! grep -q 'accounts-stats/api' "$NGINX_CONF" 2>/dev/null; then
  echo "Patching nginx-proxy.conf..."
  python3 <<'PY'
from pathlib import Path
conf = Path("/opt/nginx-proxy.conf")
snippet = Path("/opt/dashboard/deploy/nginx-atome-accounts-stats.conf")
text = conf.read_text(encoding="utf-8")
block = snippet.read_text(encoding="utf-8")
marker = "    # ── Block scanners"
if block.strip() in text:
    print("nginx already patched")
elif marker in text:
    text = text.replace(marker, block + "\n" + marker, 1)
    conf.write_text(text, encoding="utf-8")
    print("nginx patched OK")
else:
    raise SystemExit("marker not found in nginx-proxy.conf")
PY
  docker exec nginx-proxy nginx -t
  docker exec nginx-proxy nginx -s reload
else
  echo "nginx accounts-stats routes already present"
fi

cd /opt/dashboard
docker compose -f docker-compose.prod.yml -f docker-compose.prod.vps.yml up -d --build

cd /opt
docker compose build atome-web
docker compose up -d atome-web

echo "Done. Check https://atome-farm.duckdns.org/analytics (tab Аналитика аккаунтов)"
