#!/bin/bash
set -euo pipefail
REMOTE_ROOT=/home/atom/dashboard
BACKEND=$(docker ps --format '{{.Names}}' | grep '^backend-d3rx' | head -1)
FRONTEND=$(docker ps --format '{{.Names}}' | grep '^frontend-d3rx' | head -1)
if [ -z "$BACKEND" ] || [ -z "$FRONTEND" ]; then
  echo "Coolify containers not found"
  exit 1
fi
echo "backend=$BACKEND frontend=$FRONTEND"
for f in \
  accounts/models.py \
  accounts/serializers.py \
  accounts/views.py \
  accounts/urls.py \
  accounts/admin.py \
  accounts/migrations/0047_account_group_country.py; do
  docker cp "$REMOTE_ROOT/backend/$f" "$BACKEND:/app/$f"
done
docker cp "$REMOTE_ROOT/new_frontend/app.bundle.js" "$FRONTEND:/usr/share/nginx/html/app.bundle.js"
docker cp "$REMOTE_ROOT/new_frontend/app.html" "$FRONTEND:/usr/share/nginx/html/app.html"
echo "=== migrate ==="
docker exec "$BACKEND" python manage.py migrate accounts --noinput
echo "=== api check ==="
curl -sS -o /dev/null -w 'groups=%{http_code} countries=%{http_code} ui=%{http_code}\n' \
  http://127.0.0.1:9082/api/accounts/groups/ \
  http://127.0.0.1:9082/api/accounts/countries/ \
  https://dashboard-new.atom-farm.com/
