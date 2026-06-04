#!/bin/bash
# Постоянные логи dashboard на Mobile Farm: каталог, cron, logrotate (7 дней по умолчанию).
# Запуск на сервере под atom после деплоя compose с volume var/log/dashboard.
set -euo pipefail

ROOT="${DASHBOARD_ROOT:-$HOME/dashboard}"
LOG_DIR="$ROOT/var/log/dashboard"
RETENTION="${DASHBOARD_LOG_RETENTION_DAYS:-7}"
CRON_MARK="# dashboard-log-archive"

cd "$ROOT"
mkdir -p "$LOG_DIR"
chmod 755 "$ROOT/var/log" "$LOG_DIR" 2>/dev/null || true

chmod +x "$ROOT/scripts/archive-dashboard-docker-logs.sh"

# Ежечасный снимок docker logs (stderr scheduled_refresh / worker_pool).
cron_line="17 * * * * DASHBOARD_ROOT=$ROOT DASHBOARD_LOG_RETENTION_DAYS=$RETENTION $ROOT/scripts/archive-dashboard-docker-logs.sh >>$LOG_DIR/archive-cron.log 2>&1"
if crontab -l 2>/dev/null | grep -qF "$CRON_MARK"; then
  echo "==> cron уже настроен ($CRON_MARK)"
else
  (crontab -l 2>/dev/null | grep -vF "$CRON_MARK"; echo "$CRON_MARK"; echo "$cron_line") | crontab -
  echo "==> cron: ежечасный archive-dashboard-docker-logs.sh"
fi

# logrotate для backend.log (Django) и docker-backend-*.log на хосте.
if command -v logrotate >/dev/null 2>&1; then
  sudo tee /etc/logrotate.d/dashboard >/dev/null <<EOF
$LOG_DIR/*.log $LOG_DIR/backend.log.* {
    daily
    rotate $RETENTION
    missingok
    notifempty
    compress
    delaycompress
    copytruncate
}
EOF
  echo "==> /etc/logrotate.d/dashboard (rotate $RETENTION days)"
else
  echo "WARN: logrotate не установлен — удаление только через find в archive-скрипте" >&2
fi

echo ""
echo "Готово. Логи:"
echo "  Django:  $LOG_DIR/backend.log (+ backend.log.YYYY-MM-DD)"
echo "  Docker:  $LOG_DIR/docker-backend-*.log (архив cron)"
echo "  Compose: logging json-file max-file 14 (~14×100MB) для dashboard-backend"
echo ""
echo "Коммит в текущем образе:"
docker exec dashboard-backend cat /app/BUILD_COMMIT.txt 2>/dev/null || echo "  (пересоберите backend с GIT_COMMIT build-arg)"
