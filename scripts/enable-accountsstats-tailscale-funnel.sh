#!/bin/bash
# Публичный URL AccountsStats на отдельной Tailscale-ноде (не streamcut).
#
# Требуется reusable auth key с Funnel в .env:
#   TS_AUTHKEY_ACCOUNTSSTATS=tskey-auth-...
# Создать: https://login.tailscale.com/admin/settings/keys
#   — Reusable, Funnel enabled
#
#   chmod +x scripts/enable-accountsstats-tailscale-funnel.sh
#   ./scripts/enable-accountsstats-tailscale-funnel.sh
#
# URL: https://accountsstats.<tailnet>.ts.net:10000/

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

COMPOSE=(docker compose -f docker-compose.prod.yml -f docker-compose.prod.mobilefarm.yml)
HTTPS_PORT="${MOBILEFARM_FUNNEL_HTTPS_PORT:-10000}"
AUTH_USER="${DASHBOARD_BASIC_AUTH_USER:-admin}"
AUTH_PASS="${DASHBOARD_BASIC_AUTH_PASSWORD:-}"
ORIGIN="http://127.0.0.1:${DASHBOARD_PUBLIC_HTTP_PORT:-9081}"

if [[ -f .env ]]; then
  # shellcheck disable=SC1091
  set -a
  source .env
  set +a
  AUTH_USER="${DASHBOARD_BASIC_AUTH_USER:-$AUTH_USER}"
  AUTH_PASS="${DASHBOARD_BASIC_AUTH_PASSWORD:-$AUTH_PASS}"
  ORIGIN="http://127.0.0.1:${DASHBOARD_PUBLIC_HTTP_PORT:-9081}"
fi

if [[ -z "${TS_AUTHKEY_ACCOUNTSSTATS:-}" ]]; then
  echo "ERROR: задайте TS_AUTHKEY_ACCOUNTSSTATS в .env (reusable auth key с Funnel)" >&2
  echo "  https://login.tailscale.com/admin/settings/keys" >&2
  exit 1
fi

if [[ -z "$AUTH_PASS" ]]; then
  echo "ERROR: set DASHBOARD_BASIC_AUTH_PASSWORD in .env" >&2
  exit 1
fi

if ! curl -sf -u "${AUTH_USER}:${AUTH_PASS}" "${ORIGIN}/healthz/" >/dev/null; then
  echo "ERROR: dashboard not reachable at ${ORIGIN} (with auth)" >&2
  exit 1
fi

echo "==> Снимаем Funnel :${HTTPS_PORT} с ноды streamcut (если был)"
docker pull tailscale/tailscale:latest >/dev/null
docker run --rm --network host \
  -v /var/run/tailscale/tailscaled.sock:/var/run/tailscale/tailscaled.sock \
  tailscale/tailscale:latest \
  tailscale funnel --https="${HTTPS_PORT}" off 2>/dev/null || true

echo "==> Поднимаем виртуальную ноду accountsstats-tailscale"
"${COMPOSE[@]}" up -d accountsstats-tailscale

echo "==> Ждём регистрацию ноды и Funnel..."
for _ in $(seq 1 30); do
  if docker logs dashboard-accountsstats-tailscale 2>&1 | grep -qE 'logged in|Running serve|funnel'; then
    break
  fi
  sleep 2
done

PUBLIC_HOST="accountsstats.tailef595f.ts.net"
PUBLIC="https://${PUBLIC_HOST}:${HTTPS_PORT}"

mkdir -p "$ROOT/var" 2>/dev/null || true
if [[ -w "$ROOT/var" ]]; then
  printf '%s\n' "$PUBLIC" >"$ROOT/var/public_tailscale_url.txt"
  chmod 600 "$ROOT/var/public_tailscale_url.txt" 2>/dev/null || true
fi

echo ""
echo "OK: ${PUBLIC}"
echo "Login: ${AUTH_USER} / password from DASHBOARD_BASIC_AUTH_PASSWORD"
echo ""
echo "Streamcut остаётся на https://streamcut.tailef595f.ts.net/"
echo ""
echo "Проверка:"
docker logs dashboard-accountsstats-tailscale 2>&1 | tail -20
