#!/bin/bash
# Снимок stdout/stderr контейнера backend в файл на хосте (дополнение к Django backend.log).
# Удаляет архивы старше RETENTION_DAYS. Поставить в cron/systemd — setup-mobilefarm-log-retention.sh
set -euo pipefail

ROOT="${DASHBOARD_ROOT:-$HOME/dashboard}"
LOG_DIR="${DASHBOARD_HOST_LOG_DIR:-$ROOT/var/log/dashboard}"
CONTAINER="${DASHBOARD_BACKEND_CONTAINER:-dashboard-backend}"
RETENTION_DAYS="${DASHBOARD_LOG_RETENTION_DAYS:-7}"
SINCE="${DASHBOARD_LOG_ARCHIVE_SINCE:-24h}"

mkdir -p "$LOG_DIR"
stamp="$(date +%Y%m%d_%H%M%S)"
out="$LOG_DIR/docker-backend-${stamp}.log"

if ! docker ps --format '{{.Names}}' | grep -qx "$CONTAINER"; then
  echo "[archive-dashboard-docker-logs] контейнер $CONTAINER не запущен, пропуск" >&2
  exit 0
fi

{
  echo "# archived $(date -Iseconds) container=$CONTAINER since=$SINCE"
  docker logs "$CONTAINER" --since "$SINCE" 2>&1
} >>"$out"

find "$LOG_DIR" -maxdepth 1 -name 'docker-backend-*.log' -type f -mtime +"$RETENTION_DAYS" -delete
echo "[archive-dashboard-docker-logs] OK $out"
