# Задаёт статический DNS на интерфейсе (по умолчанию Ethernet): 1.1.1.1 и 8.8.8.8.
# Требуются права администратора. Запуск:
#   ПКМ на PowerShell → «Запуск от имени администратора», затем:
#   Set-Location "…\dashboard\tools"; .\set-ethernet-dns.ps1
# Откат на DNS от DHCP (роутер):
#   Set-DnsClientServerAddress -InterfaceAlias "<имя>" -ResetServerAddresses

param(
    [string] $InterfaceAlias = "Ethernet",
    [string[]] $ServerAddresses = @("1.1.1.1", "8.8.8.8")
)

$ErrorActionPreference = "Stop"
if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Error "Запустите этот скрипт из PowerShell от имени администратора."
    exit 1
}

$iface = Get-NetAdapter -Name $InterfaceAlias -ErrorAction SilentlyContinue
if (-not $iface) {
    Write-Host "Адаптер '$InterfaceAlias' не найден. Доступные:" -ForegroundColor Yellow
    Get-NetAdapter | Where-Object Status -eq "Up" | Select-Object Name, InterfaceDescription | Format-Table -AutoSize
    exit 1
}

Write-Host "Интерфейс: $InterfaceAlias → DNS: $($ServerAddresses -join ', ')" -ForegroundColor Cyan
Set-DnsClientServerAddress -InterfaceAlias $InterfaceAlias -ServerAddresses $ServerAddresses
Get-DnsClientServerAddress -InterfaceAlias $InterfaceAlias -AddressFamily IPv4 | Format-List InterfaceAlias, ServerAddresses
Write-Host "Готово. Проверка: nslookup <ваш>.trycloudflare.com" -ForegroundColor Green
