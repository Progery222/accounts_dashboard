#!/bin/sh
set -e

USER="${DASHBOARD_BASIC_AUTH_USER:-admin}"
PASS="${DASHBOARD_BASIC_AUTH_PASSWORD:-}"

if [ -z "$PASS" ]; then
  echo "ERROR: DASHBOARD_BASIC_AUTH_PASSWORD is required for nginx public listener on port 81" >&2
  exit 1
fi

HASH="$(openssl passwd -apr1 "$PASS")"
printf '%s:%s\n' "$USER" "$HASH" > /etc/nginx/.htpasswd
chmod 644 /etc/nginx/.htpasswd

exec "$@"
