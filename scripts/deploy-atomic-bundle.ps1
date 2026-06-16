# Быстрая заливка Atomic UI (app.bundle.js + app.html) на 10.20.87.230 → dashboard-frontend.
# Использование: .\scripts\deploy-atomic-bundle.ps1

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Bundle = Join-Path $Root "new_frontend\app.bundle.js"
$AppHtml = Join-Path $Root "new_frontend\app.html"
$Identity = if ($env:ATOMIC_SSH_IDENTITY) { $env:ATOMIC_SSH_IDENTITY } else { "$env:USERPROFILE\.ssh\id_ed25519" }
$Remote = if ($env:ATOMIC_DEPLOY_HOST) { $env:ATOMIC_DEPLOY_HOST } else { "atom@10.20.87.230" }
$RemoteBundle = "/home/atom/dashboard/new_frontend/app.bundle.js"
$RemoteHtml = "/home/atom/dashboard/new_frontend/app.html"
$Container = "dashboard-frontend"
$ContainerBundle = "/usr/share/nginx/html/app.bundle.js"
$ContainerHtml = "/usr/share/nginx/html/app.html"

Write-Host "Checking syntax: $Bundle"
node --check $Bundle
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "Uploading to $Remote ..."
scp -i $Identity -o BatchMode=yes $Bundle "${Remote}:${RemoteBundle}"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
scp -i $Identity -o BatchMode=yes $AppHtml "${Remote}:${RemoteHtml}"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "Copying into container $Container ..."
ssh -i $Identity -o BatchMode=yes $Remote "docker cp $RemoteBundle ${Container}:${ContainerBundle} && docker cp $RemoteHtml ${Container}:${ContainerHtml}"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "OK: http://10.20.87.230:9080/emu-settings (Ctrl+Shift+R)"
