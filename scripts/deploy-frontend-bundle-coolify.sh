#!/bin/bash
set -euo pipefail
REMOTE_ROOT=/home/atom/dashboard
FRONTEND=$(docker ps --format '{{.Names}}' | grep -E '^frontend-d3rx|^dashboard-frontend' | head -1)
if [ -z "$FRONTEND" ]; then
  echo "Frontend container not found"
  exit 1
fi
echo "frontend=$FRONTEND"
docker cp "$REMOTE_ROOT/frontend/index.html" "$FRONTEND:/usr/share/nginx/html/index.html"
docker exec -u root "$FRONTEND" sh -c 'nginx -t && nginx -s reload'
curl -sS -o /dev/null -w 'ui=%{http_code}\n' https://dashboard-new.atom-farm.com/
