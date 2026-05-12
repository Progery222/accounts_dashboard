# Держит Quick Tunnel живым: при падении cloudflared перезапускает через 5 с.
# URL вида https://….trycloudflare.com — без своего домена и без DNS.
# Запуск: powershell -NoExit -File "...\new_frontend\tunnel-keepalive.ps1"
# Нужны: run_server.py на 5174 и Django на 8000.
$ErrorActionPreference = "Continue"
$root = $PSScriptRoot
$config = Join-Path $root "cloudflared.new-frontend.yml"
$cf = "${env:ProgramFiles(x86)}\cloudflared\cloudflared.exe"
if (-not (Test-Path $cf)) {
  $cf = "cloudflared"
}
while ($true) {
  Write-Host ("[{0}] cloudflared quick tunnel…" -f (Get-Date -Format "HH:mm:ss"))
  Set-Location $root
  & $cf tunnel --config $config --url http://127.0.0.1:5174
  Write-Host ("[{0}] cloudflared exit {1}, пауза 5 с" -f (Get-Date -Format "HH:mm:ss"), $LASTEXITCODE)
  Start-Sleep -Seconds 5
}
