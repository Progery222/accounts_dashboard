# Quick Tunnel → AccountsStats (new_frontend) на 127.0.0.1:5174 + /api → Django.
# По умолчанию API :8000. Если задать $env:ATOMIC_TUNNEL_API_PORT = "8010" — конфиг с :8010.
# Перед запуском: new_frontend — npm run dev; Django — runserver на выбранном порту.
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location (Join-Path $root "new_frontend")
$apiPort = ($env:ATOMIC_TUNNEL_API_PORT -as [string]).Trim()
$config = if ($apiPort -eq "8010") { "cloudflared.5174.8010.yml" } else { "cloudflared.5174.yml" }
cloudflared tunnel --config $config --url http://127.0.0.1:5174
