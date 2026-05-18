# Основной Django: API + APScheduler (автообновление по расписанию).
$ErrorActionPreference = "Stop"
$ports = Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue |
    Select-Object -ExpandProperty OwningProcess -Unique
foreach ($p in $ports) {
    Stop-Process -Id $p -Force -ErrorAction SilentlyContinue
}
Start-Sleep -Seconds 1
Set-Location (Join-Path $PSScriptRoot ".." "backend")
$env:RUN_SCHEDULER = "true"
py -3.13 -m poetry run python manage.py runserver 127.0.0.1:8000
