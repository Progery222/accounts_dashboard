# Quick Tunnel → Vite «Подписчики» (subs) на 127.0.0.1:5180.
# Перед запуском: из subs/frontend — npm run dev; Django :8000 (прокси /api с 5180).
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location (Join-Path $root "subs\frontend")
cloudflared tunnel --config cloudflared.5180.yml --url http://127.0.0.1:5180
