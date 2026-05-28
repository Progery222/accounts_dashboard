#!/bin/bash
# Первичная подготовка GPU-сервера (запуск на 10.20.87.230 под пользователем atom).
set -euo pipefail

echo "==> Docker (apt: на чистом Ubuntu часто нет curl)"
if ! command -v docker >/dev/null 2>&1; then
  sudo apt-get update
  sudo DEBIAN_FRONTEND=noninteractive apt-get install -y docker.io docker-compose-v2 curl
  sudo systemctl enable --now docker
  sudo usermod -aG docker "$USER"
  echo "Docker installed. Выйдите из SSH и зайдите снова (или: newgrp docker), затем деплой с Windows."
  exit 0
fi
docker compose version >/dev/null 2>&1 || {
  echo "Install: sudo apt install docker-compose-v2"
  exit 1
}

echo "==> Firewall (optional)"
if command -v ufw >/dev/null 2>&1 && sudo ufw status 2>/dev/null | grep -q inactive; then
  echo "ufw inactive — skip"
elif command -v ufw >/dev/null 2>&1; then
  sudo ufw allow 9080/tcp comment 'accounts-stats' || true
fi

mkdir -p "$HOME/dashboard"
echo "OK: $HOME/dashboard ready. Run deploy from Windows: .\\scripts\\deploy-mobilefarm.ps1"
