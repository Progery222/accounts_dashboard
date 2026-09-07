#!/bin/bash
# Hot-patch Coolify backend with Patchright + curl_cffi + challenge solvers.
# Run on Coolify host (10.25.21.190) after downloading the deploy tarball:
#   curl -fsSL http://10.25.21.149:8765/scrape-stack.tgz -o /tmp/scrape-stack.tgz
#   bash /tmp/apply-scrape-stack-coolify.sh
set -euo pipefail

REMOTE_ROOT="${REMOTE_ROOT:-/home/atom/dashboard}"
TGZ="${1:-/tmp/scrape-stack.tgz}"
BACKEND=$(docker ps --format '{{.Names}}' | grep -E '^backend-d3rx|^dashboard-backend' | head -1 || true)
if [ -z "${BACKEND}" ]; then
  echo "backend container not found"
  docker ps --format '{{.Names}}'
  exit 1
fi
echo "backend=$BACKEND"

if [ ! -f "$TGZ" ]; then
  echo "missing tarball: $TGZ"
  exit 1
fi

mkdir -p "$REMOTE_ROOT"
tar -xzf "$TGZ" -C "$REMOTE_ROOT"

# Sync Python tree into running container (adopt-in-place).
docker cp "$REMOTE_ROOT/backend/platforms/." "$BACKEND:/app/platforms/"
docker cp "$REMOTE_ROOT/backend/accounts/instagram_worker.py" "$BACKEND:/app/accounts/instagram_worker.py"
docker cp "$REMOTE_ROOT/backend/accounts/telegram_worker.py" "$BACKEND:/app/accounts/telegram_worker.py"
docker cp "$REMOTE_ROOT/backend/accounts/threads_worker.py" "$BACKEND:/app/accounts/threads_worker.py"
docker cp "$REMOTE_ROOT/backend/accounts/x_worker.py" "$BACKEND:/app/accounts/x_worker.py"
docker cp "$REMOTE_ROOT/backend/accounts/settings_views.py" "$BACKEND:/app/accounts/settings_views.py"
docker cp "$REMOTE_ROOT/backend/accounts/management/commands/setup_tiktok_auth.py" "$BACKEND:/app/accounts/management/commands/setup_tiktok_auth.py"
docker cp "$REMOTE_ROOT/backend/tiktok_app/playwright_worker.py" "$BACKEND:/app/tiktok_app/playwright_worker.py"
docker cp "$REMOTE_ROOT/backend/config/settings.py" "$BACKEND:/app/config/settings.py"
docker cp "$REMOTE_ROOT/backend/config/worker_accounts.env.example" "$BACKEND:/app/config/worker_accounts.env.example"
docker cp "$REMOTE_ROOT/backend/requirements.txt" "$BACKEND:/app/requirements.txt"

# Env for browser engine (host bind-mounted worker_accounts.env if present).
ENV_FILE="$REMOTE_ROOT/backend/config/worker_accounts.env"
if [ -f "$ENV_FILE" ]; then
  grep -q '^BROWSER_ENGINE=' "$ENV_FILE" 2>/dev/null || echo 'BROWSER_ENGINE=patchright' >>"$ENV_FILE"
  grep -q '^CURL_CFFI_ENABLED=' "$ENV_FILE" 2>/dev/null || echo 'CURL_CFFI_ENABLED=true' >>"$ENV_FILE"
  # force values
  sed -i 's/^BROWSER_ENGINE=.*/BROWSER_ENGINE=patchright/' "$ENV_FILE" || true
  sed -i 's/^CURL_CFFI_ENABLED=.*/CURL_CFFI_ENABLED=true/' "$ENV_FILE" || true
  docker cp "$ENV_FILE" "$BACKEND:/app/config/worker_accounts.env" || true
fi

echo "=== pip install patchright curl_cffi ==="
docker exec -u root "$BACKEND" pip install -q 'patchright==1.62.3' 'curl_cffi>=0.16.3'
echo "=== patchright install chromium ==="
docker exec -u root "$BACKEND" python -m patchright install chromium

echo "=== restart backend ==="
docker restart "$BACKEND"
sleep 8
echo "=== smoke ==="
docker exec "$BACKEND" python -c "from platforms.browser_engine import browser_engine_name; print('engine', browser_engine_name())"
docker exec "$BACKEND" python -c "from platforms.http_client import HttpClient; c=HttpClient(timeout=15); r=c.get('https://httpbin.org/headers'); print(c.backend, r.status_code); c.close()"
curl -sS -o /dev/null -w 'api=%{http_code}\n' http://127.0.0.1:9082/api/accounts/?page_size=1 || true
echo DONE
