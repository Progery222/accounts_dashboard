#!/bin/bash
# Режим по умолчанию: Playwright в Docker на Xvfb :99 (RDP не нужен для refresh).
# Можно запускать по SSH. RDP для ручной работы остаётся доступен отдельно.
#
# Вернуть окна на экран RDP: ./scripts/enable-mobilefarm-headed-browser.sh
set -euo pipefail

ROOT="${DASHBOARD_ROOT:-$HOME/dashboard}"
cd "$ROOT"
disp=":99"

echo "==> Режим Xvfb (DISPLAY=$disp)"

if ! command -v Xvfb >/dev/null 2>&1; then
  echo "==> Установка пакета xvfb"
  sudo DEBIAN_FRONTEND=noninteractive apt-get update
  sudo DEBIAN_FRONTEND=noninteractive apt-get install -y xvfb
fi

svc_src="$ROOT/scripts/mobilefarm-xvfb.service"
if [[ -f "$svc_src" ]]; then
  echo "==> systemd: mobilefarm-xvfb"
  sudo cp "$svc_src" /etc/systemd/system/mobilefarm-xvfb.service
  sudo systemctl daemon-reload
  sudo systemctl enable --now mobilefarm-xvfb
  sleep 1
  if ! sudo systemctl is-active --quiet mobilefarm-xvfb; then
    echo "WARN: mobilefarm-xvfb не active — проверьте: sudo systemctl status mobilefarm-xvfb" >&2
  fi
else
  echo "WARN: нет $svc_src — запускаю разовый Xvfb" >&2
  if ! pgrep -f "Xvfb $disp" >/dev/null 2>&1; then
    nohup Xvfb "$disp" -screen 0 1920x1080x24 -nolisten tcp -ac >/tmp/mobilefarm-xvfb.log 2>&1 &
    sleep 1
  fi
fi

if [[ ! -S "/tmp/.X11-unix/X${disp#:}" ]]; then
  echo "ERROR: сокет /tmp/.X11-unix/X${disp#:} не найден" >&2
  exit 1
fi

wa="$ROOT/backend/config/worker_accounts.env"
if [[ -f "$wa" ]]; then
  grep -v '^ACCOUNTS_BROWSER_HEADLESS=' "$wa" > "${wa}.tmp" || true
  {
    cat "${wa}.tmp"
    echo "ACCOUNTS_BROWSER_HEADLESS=false"
    echo "ACCOUNTS_AUTOREFRESH_PREWARM_PLAYWRIGHT=true"
  } > "$wa"
  rm -f "${wa}.tmp"
  chmod 600 "$wa"
fi

touch "$ROOT/.env"
set_env() {
  local key="$1" val="$2"
  if grep -q "^${key}=" "$ROOT/.env"; then
    sed -i "s|^${key}=.*|${key}=${val}|" "$ROOT/.env"
  else
    echo "${key}=${val}" >> "$ROOT/.env"
  fi
}
set_env MOBILEFARM_DISPLAY "$disp"
set_env MOBILEFARM_HEADED_BROWSER 1
set_env MOBILEFARM_BROWSER_MODE xvfb
set_env BROWSER_HEADLESS false
chmod 600 "$ROOT/.env"

compose() {
  if groups | grep -qw docker; then
    docker compose -f docker-compose.prod.yml -f docker-compose.prod.mobilefarm.yml "$@"
  else
    sudo docker compose -f docker-compose.prod.yml -f docker-compose.prod.mobilefarm.yml "$@"
  fi
}

echo "==> Перезапуск backend (Xvfb $disp)"
compose up -d backend

sleep 4
echo "==> Проверка"
docker exec dashboard-backend sh -c 'echo DISPLAY=$DISPLAY BROWSER_HEADLESS=$BROWSER_HEADLESS; ls -l /tmp/.X11-unix/X99 2>/dev/null || ls /tmp/.X11-unix/ | head -3'

echo ""
echo "OK. Refresh/TikTok идут на Xvfb $disp — RDP для этого не нужен."
echo "Окна на монитор RDP: ./scripts/enable-mobilefarm-headed-browser.sh (из RDP-терминала)."
