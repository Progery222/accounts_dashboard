# Второй Django для туннеля /api→:8010 — без планировщика (cron только на :8000).
$ErrorActionPreference = "Stop"
$ports = Get-NetTCPConnection -LocalPort 8010 -State Listen -ErrorAction SilentlyContinue |
    Select-Object -ExpandProperty OwningProcess -Unique
foreach ($p in $ports) {
    Stop-Process -Id $p -Force -ErrorAction SilentlyContinue
}
Start-Sleep -Seconds 1
Set-Location (Join-Path $PSScriptRoot ".." "backend")
$env:RUN_SCHEDULER = "false"
py -3.13 -m poetry run python manage.py runserver 127.0.0.1:8010
