#!/bin/bash
# Run on Coolify host 10.25.21.190 (Execute Command / SSH) after reboot
# when frontend container came back with old baked-in app.bundle.js.
set -euo pipefail
REMOTE_ROOT=/home/atom/dashboard
FRONTEND=$(docker ps --format '{{.Names}}' | grep '^frontend-d3rx' | head -1)
BACKEND=$(docker ps --format '{{.Names}}' | grep '^backend-d3rx' | head -1)
if [ -z "${FRONTEND}" ]; then
  echo "frontend-d3rx container not running"
  docker ps -a --format '{{.Names}} {{.Status}}' | head -40
  exit 1
fi
echo "frontend=$FRONTEND backend=${BACKEND:-none}"
mkdir -p "$REMOTE_ROOT/new_frontend"
curl -fsSL -o "$REMOTE_ROOT/new_frontend/app.bundle.js" \
  "https://raw.githubusercontent.com/Progery222/accounts_dashboard/master/new_frontend/app.bundle.js"
curl -fsSL -o "$REMOTE_ROOT/new_frontend/app.html" \
  "https://raw.githubusercontent.com/Progery222/accounts_dashboard/master/new_frontend/app.html"
docker cp "$REMOTE_ROOT/new_frontend/app.bundle.js" "$FRONTEND:/usr/share/nginx/html/app.bundle.js"
docker cp "$REMOTE_ROOT/new_frontend/app.html" "$FRONTEND:/usr/share/nginx/html/app.html"
# also index.html if present as SPA entry
if docker exec "$FRONTEND" test -f /usr/share/nginx/html/index.html; then
  docker cp "$REMOTE_ROOT/new_frontend/app.html" "$FRONTEND:/usr/share/nginx/html/index.html" || true
fi
echo "markers:"
grep -c TopBarOwnersDropdown "$REMOTE_ROOT/new_frontend/app.bundle.js" || true
grep -c renderCatalogList "$REMOTE_ROOT/new_frontend/app.bundle.js" || true
curl -sS -o /dev/null -w 'ui=%{http_code} api=%{http_code}\n' \
  http://127.0.0.1:9082/ \
  http://127.0.0.1:9082/api/accounts/
echo "OK — soft-refresh browser (Ctrl+F5)"
