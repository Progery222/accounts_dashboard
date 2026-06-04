#!/bin/bash
# Временный режим: окна Playwright на экране RDP (не Xvfb).
# Запускать только из RDP/XFCE-терминала (echo $DISPLAY → обычно :10 или :10.0).
#
# Вернуть фоновый режим без RDP: ./scripts/enable-mobilefarm-xvfb.sh
set -euo pipefail

ROOT="${DASHBOARD_ROOT:-$HOME/dashboard}"
cd "$ROOT"

# Запускать только из RDP/XFCE-терминала (не из голого SSH без DISPLAY).
disp="${DISPLAY:-}"
if [[ -z "$disp" ]]; then
  if [[ -f "$ROOT/.env" ]] && grep -q '^MOBILEFARM_DISPLAY=' "$ROOT/.env"; then
    disp="$(grep '^MOBILEFARM_DISPLAY=' "$ROOT/.env" | tail -1 | cut -d= -f2-)"
  fi
fi
disp="${disp:-:0}"
xauth="${XAUTHORITY:-$HOME/.Xauthority}"
echo "==> DISPLAY=$disp XAUTHORITY=$xauth"
if [[ -z "${DISPLAY:-}" ]]; then
  echo "WARN: DISPLAY не задан в этой сессии — убедитесь, что disp=$disp совпадает с RDP (echo \$DISPLAY)." >&2
fi

if command -v xhost >/dev/null 2>&1; then
  xhost +local:docker 2>/dev/null || true
  xhost +local:root 2>/dev/null || true
  xhost +SI:localuser:docker 2>/dev/null || true
fi

# worker_accounts: одна строка headed (как локальная Windows)
wa="$ROOT/backend/config/worker_accounts.env"
if [[ -f "$wa" ]]; then
  grep -v -E '^(ACCOUNTS_BROWSER_HEADLESS|TIKTOK_FORCE_WORKER)=' "$wa" > "${wa}.tmp" || true
  {
    cat "${wa}.tmp"
    echo "ACCOUNTS_BROWSER_HEADLESS=false"
    echo "ACCOUNTS_AUTOREFRESH_PREWARM_PLAYWRIGHT=true"
    echo "TIKTOK_FORCE_WORKER=true"
  } > "$wa"
  rm -f "${wa}.tmp"
  chmod 600 "$wa"
fi

# .env: headed + DISPLAY для compose
touch "$ROOT/.env"
if grep -q '^MOBILEFARM_DISPLAY=' "$ROOT/.env"; then
  sed -i "s|^MOBILEFARM_DISPLAY=.*|MOBILEFARM_DISPLAY=$disp|" "$ROOT/.env"
else
  echo "MOBILEFARM_DISPLAY=$disp" >> "$ROOT/.env"
fi
if grep -q '^MOBILEFARM_HEADED_BROWSER=' "$ROOT/.env"; then
  sed -i 's|^MOBILEFARM_HEADED_BROWSER=.*|MOBILEFARM_HEADED_BROWSER=1|' "$ROOT/.env"
else
  echo "MOBILEFARM_HEADED_BROWSER=1" >> "$ROOT/.env"
fi
if grep -q '^MOBILEFARM_BROWSER_MODE=' "$ROOT/.env"; then
  sed -i 's|^MOBILEFARM_BROWSER_MODE=.*|MOBILEFARM_BROWSER_MODE=rdp|' "$ROOT/.env"
else
  echo "MOBILEFARM_BROWSER_MODE=rdp" >> "$ROOT/.env"
fi
if grep -q '^BROWSER_HEADLESS=' "$ROOT/.env"; then
  sed -i 's|^BROWSER_HEADLESS=.*|BROWSER_HEADLESS=false|' "$ROOT/.env"
else
  echo "BROWSER_HEADLESS=false" >> "$ROOT/.env"
fi
set_env_key() {
  local key="$1" val="$2"
  if grep -q "^${key}=" "$ROOT/.env"; then
    sed -i "s|^${key}=.*|${key}=${val}|" "$ROOT/.env"
  else
    echo "${key}=${val}" >> "$ROOT/.env"
  fi
}
set_env_key TIKTOK_FORCE_WORKER true
if grep -q '^XAUTHORITY=' "$ROOT/.env"; then
  sed -i "s|^XAUTHORITY=.*|XAUTHORITY=$xauth|" "$ROOT/.env"
else
  echo "XAUTHORITY=$xauth" >> "$ROOT/.env"
fi
chmod 600 "$ROOT/.env"

compose() {
  if groups | grep -qw docker; then
    docker compose -f docker-compose.prod.yml -f docker-compose.prod.mobilefarm.yml "$@"
  else
    sudo docker compose -f docker-compose.prod.yml -f docker-compose.prod.mobilefarm.yml "$@"
  fi
}

echo "==> Перезапуск backend (headed, X11)"
compose up -d --build backend

sleep 4
echo "==> Проверка env в контейнере"
docker exec dashboard-backend sh -c 'echo DISPLAY=$DISPLAY XAUTHORITY=$XAUTHORITY BROWSER_HEADLESS=$BROWSER_HEADLESS PLAYWRIGHT_BROWSERS_PATH=$PLAYWRIGHT_BROWSERS_PATH; ls -l /ms-playwright/chromium*/chrome-linux64/chrome 2>/dev/null | head -1; grep ACCOUNTS_BROWSER_HEADLESS /app/config/worker_accounts.env | tail -1'

echo ""
echo "OK. Окно Chromium при «Обновить» — на этом RDP-экране ($disp)."
echo "Вернуть Xvfb (без окон на RDP): ./scripts/enable-mobilefarm-xvfb.sh"
echo "Если окна нет: echo \$DISPLAY в RDP, подставьте в MOBILEFARM_DISPLAY в .env, compose up -d backend."
