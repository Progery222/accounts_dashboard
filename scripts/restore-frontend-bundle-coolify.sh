#!/bin/bash
# Run on Coolify host 10.25.21.190 after reboot / container recreate
set -euo pipefail
REMOTE_ROOT="${REMOTE_ROOT:-/home/atom/dashboard}"
FRONTEND=$(docker ps --format '{{.Names}}' | grep -E '^frontend-d3rx|^dashboard-frontend' | head -1 || true)
if [ -z "${FRONTEND}" ]; then
  echo "frontend container not found"
  docker ps --format '{{.Names}}'
  exit 1
fi
echo "frontend=$FRONTEND"
test -f "$REMOTE_ROOT/frontend/index.html"
docker cp "$REMOTE_ROOT/frontend/index.html" "$FRONTEND:/usr/share/nginx/html/index.html"
docker cp "$REMOTE_ROOT/deploy/nginx-atomic/default.conf" "$FRONTEND:/etc/nginx/conf.d/default.conf" 2>/dev/null || true
docker cp "$REMOTE_ROOT/deploy/nginx-atomic/dashboard-locations.inc" "$FRONTEND:/etc/nginx/conf.d/dashboard-locations.inc" 2>/dev/null || true
docker exec -u root "$FRONTEND" sh -c 'nginx -t && nginx -s reload'
curl -sS -o /dev/null -w 'ui=%{http_code}\n' http://127.0.0.1:9082/
echo OK
