#!/bin/bash
# УСТАРЕЛО: Cloudflare Quick Tunnel для дашборда отключён — используйте Tailscale Funnel
# (scripts/enable-mobilefarm-tailscale-funnel.sh).

set -euo pipefail
echo "Cloudflare tunnel для дашборда отключён." >&2
echo "Используйте: ./scripts/enable-accountsstats-tailscale-funnel.sh" >&2
echo "URL: https://accountsstats.tailef595f.ts.net:10000/" >&2
exit 1

# --- legacy below (не запускается) ---
#
# Запуск на сервере (пользователь atom, из ~/dashboard):
#   chmod +x scripts/enable-mobilefarm-public-tunnel.sh
#   ./scripts/enable-mobilefarm-public-tunnel.sh
#
# URL меняется при пересоздании контейнера. Для постоянного hostname см.
# scripts/enable-mobilefarm-tailscale-funnel.sh

set -euo pipefail

PORT="${DASHBOARD_PUBLIC_HTTP_PORT:-9081}"
ORIGIN="http://127.0.0.1:${PORT}"
NAME="${DASHBOARD_TUNNEL_CONTAINER:-dashboard-cloudflared}"
URL_FILE="${DASHBOARD_PUBLIC_URL_FILE:-$HOME/dashboard/var/public_tunnel_url.txt}"

if ! curl -sf "${ORIGIN}/healthz/" >/dev/null; then
  echo "ERROR: dashboard not reachable at ${ORIGIN} (is docker compose up?)" >&2
  exit 1
fi

mkdir -p "$(dirname "$URL_FILE")"

echo "==> Pull cloudflared image (if needed)"
docker pull cloudflare/cloudflared:latest

echo "==> Restart tunnel container: ${NAME} -> ${ORIGIN}"
docker rm -f "$NAME" 2>/dev/null || true
docker run -d \
  --name "$NAME" \
  --restart unless-stopped \
  --network host \
  cloudflare/cloudflared:latest \
  tunnel --no-autoupdate --url "$ORIGIN"

echo "==> Waiting for public URL..."
PUBLIC_URL=""
for _ in $(seq 1 30); do
  PUBLIC_URL="$(docker logs "$NAME" 2>&1 | grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' | tail -1 || true)"
  if [[ -n "$PUBLIC_URL" ]]; then
    break
  fi
  sleep 1
done

if [[ -z "$PUBLIC_URL" ]]; then
  echo "WARN: could not parse URL from logs. Run: docker logs $NAME" >&2
  exit 1
fi

printf '%s\n' "$PUBLIC_URL" >"$URL_FILE"
chmod 600 "$URL_FILE" 2>/dev/null || true

echo ""
echo "OK: dashboard is public at:"
echo "  ${PUBLIC_URL}"
echo "  ${PUBLIC_URL}/emu-settings"
echo ""
echo "Saved to: ${URL_FILE}"
echo "Django already allows *.trycloudflare.com (ALLOWED_HOSTS / CSRF)."
