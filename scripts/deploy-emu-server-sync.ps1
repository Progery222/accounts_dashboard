# Деплой синхронизации настроек TV-эмуляции (API + app.bundle.js).
# Запускать с ПК в сети Mobile Farm: .\scripts\deploy-emu-server-sync.ps1

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Identity = if ($env:ATOMIC_SSH_IDENTITY) { $env:ATOMIC_SSH_IDENTITY } else { "$env:USERPROFILE\.ssh\id_ed25519" }
$Remote = if ($env:ATOMIC_DEPLOY_HOST) { $env:ATOMIC_DEPLOY_HOST } else { "atom@10.20.87.230" }
$RemoteRoot = "/home/atom/dashboard"

Write-Host "==> Syntax check app.bundle.js"
node --check (Join-Path $Root "new_frontend\app.bundle.js")

Write-Host "==> SSH probe $Remote"
ssh -i $Identity -o BatchMode=yes -o ConnectTimeout=15 $Remote "echo SSH OK"
if ($LASTEXITCODE -ne 0) {
    Write-Host "SSH unreachable. Check VPN and that 10.20.87.230 is on the network." -ForegroundColor Red
    exit 1
}

Write-Host "==> Upload backend (tv-emu-config API)"
$backendFiles = @(
    "accounts\tv_emu_config.py",
    "accounts\views.py",
    "accounts\urls.py"
)
foreach ($rel in $backendFiles) {
    $local = Join-Path $Root "backend\$rel"
    scp -i $Identity -o BatchMode=yes $local "${Remote}:${RemoteRoot}/backend/$($rel -replace '\\','/')"
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

Write-Host "==> Upload app.bundle.js"
& (Join-Path $Root "scripts\deploy-atomic-bundle.ps1")
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "==> Rebuild backend container"
ssh -i $Identity -o BatchMode=yes $Remote @"
cd $RemoteRoot && if groups | grep -qw docker; then
  docker compose -f docker-compose.prod.yml -f docker-compose.prod.mobilefarm.yml up -d --build backend
else
  sudo docker compose -f docker-compose.prod.yml -f docker-compose.prod.mobilefarm.yml up -d --build backend
fi
"@
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "==> Health + tv-emu-config API"
Start-Sleep -Seconds 6
ssh -i $Identity -o BatchMode=yes $Remote "curl -sf http://127.0.0.1:9080/healthz/ && echo && curl -s http://127.0.0.1:9080/api/accounts/tv-emu-config/ | head -c 200"

Write-Host ""
Write-Host "OK: http://10.20.87.230:9080/emu-settings - Save on PC, hard-refresh on TV." -ForegroundColor Green
