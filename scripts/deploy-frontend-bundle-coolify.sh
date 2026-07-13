#!/bin/bash
set -euo pipefail
REMOTE_ROOT=/home/atom/dashboard
FRONTEND=$(docker ps --format '{{.Names}}' | grep '^frontend-d3rx' | head -1)
if [ -z "$FRONTEND" ]; then
  echo "Frontend container not found"
  exit 1
fi
echo "frontend=$FRONTEND"
docker cp "$REMOTE_ROOT/new_frontend/app.bundle.js" "$FRONTEND:/usr/share/nginx/html/app.bundle.js"
curl -sS -o /dev/null -w 'ui=%{http_code}\n' https://dashboard-new.atom-farm.com/
