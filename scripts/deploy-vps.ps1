#Requires -Version 5.1
<#
.SYNOPSIS
  Деплой dashboard на VPS 91.84.102.27: синхронизация файлов + docker compose build.

.DESCRIPTION
  1) Копирует в staging только нужные каталоги (без .env, venv, __pycache__, var).
  2) scp на /opt/dashboard.
  3) Удаляет случайный backend/.env на сервере (иначе DATABASE_URL=localhost ломает БД).
  4) docker compose -f docker-compose.prod.yml -f docker-compose.prod.vps.yml up -d --build.

.PARAMETER Target
  all | backend | frontend — что пересобирать.

.PARAMETER SkipBuild
  Только синхронизация файлов, без docker compose.

.PARAMETER DryRun
  Показать команды без выполнения.

.EXAMPLE
  .\scripts\deploy-vps.ps1

.EXAMPLE
  .\scripts\deploy-vps.ps1 -Target backend

.EXAMPLE
  .\scripts\deploy-vps.ps1 -DryRun
#>
[CmdletBinding()]
param(
    [string]$SshHost = "91.84.102.27",
    [string]$SshUser = "root",
    [string]$IdentityFile = "$env:USERPROFILE\.ssh\id_atome",
    [string]$RemoteRoot = "/opt/dashboard",
    [ValidateSet("all", "backend", "frontend")]
    [string]$Target = "all",
    [switch]$SkipBuild,
    [switch]$DryRun
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Write-Step([string]$Message) {
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Invoke-DeployCommand([string]$Command, [switch]$AllowRobocopyCodes) {
    if ($DryRun) {
        Write-Host "[dry-run] $Command" -ForegroundColor DarkGray
        return
    }
    Invoke-Expression $Command
    if ($AllowRobocopyCodes) {
        if ($LASTEXITCODE -gt 7) {
            throw "Command failed ($LASTEXITCODE): $Command"
        }
        return
    }
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed ($LASTEXITCODE): $Command"
    }
}

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$staging = Join-Path $env:TEMP ("dashboard-deploy-{0}" -f [guid]::NewGuid().ToString("N"))
$remote = "${SshUser}@${SshHost}"
$sshBase = "ssh -i `"$IdentityFile`" -o BatchMode=yes -o ConnectTimeout=15 $remote"
$scpBase = "scp -i `"$IdentityFile`" -o BatchMode=yes"

if (-not (Test-Path $IdentityFile)) {
    throw "SSH key not found: $IdentityFile"
}

$robocopyExcludeDirs = @(".venv", ".venv-gil", "__pycache__", "var", "staticfiles", "node_modules")
$robocopyExcludeFiles = @(".env", "worker_accounts.env", "worker_subs.env", "*.pyc", "*.session")

try {
    Write-Step "Repository: $repoRoot"
    Write-Step "Staging: $staging"
    New-Item -ItemType Directory -Path $staging -Force | Out-Null

    $backendStage = Join-Path $staging "backend"
    $newFrontendStage = Join-Path $staging "new_frontend"
    $deployStage = Join-Path $staging "deploy"

    Write-Step "Copy backend/ (without secrets and caches)"
    $backendSrc = Join-Path $repoRoot "backend"
    if (-not (Test-Path $backendSrc)) {
        throw "Missing $backendSrc"
    }
    $xd = ($robocopyExcludeDirs | ForEach-Object { "/XD", $_ }) -join " "
    $xf = ($robocopyExcludeFiles | ForEach-Object { "/XF", $_ }) -join " "
    $robocopyCmd = "robocopy `"$backendSrc`" `"$backendStage`" /E /NFL /NDL /NJH /NJS /NC /NS $xd $xf"
    Invoke-DeployCommand $robocopyCmd -AllowRobocopyCodes

    foreach ($pair in @(
            @{ Name = "new_frontend"; Src = "new_frontend"; Dst = $newFrontendStage }
            @{ Name = "deploy"; Src = "deploy"; Dst = $deployStage }
        )) {
        $srcPath = Join-Path $repoRoot $pair.Src
        if (-not (Test-Path $srcPath)) {
            throw "Missing $srcPath"
        }
        Write-Step "Copy $($pair.Name)/"
        $xdOnly = ($robocopyExcludeDirs | ForEach-Object { "/XD", $_ }) -join " "
        $robocopyOne = "robocopy `"$srcPath`" `"$($pair.Dst)`" /E /NFL /NDL /NJH /NJS /NC /NS $xdOnly"
        Invoke-DeployCommand $robocopyOne -AllowRobocopyCodes
    }

    foreach ($composeFile in @("docker-compose.prod.yml", "docker-compose.prod.vps.yml")) {
        $srcCompose = Join-Path $repoRoot $composeFile
        if (-not (Test-Path $srcCompose)) {
            throw "Missing $srcCompose"
        }
        Copy-Item -Path $srcCompose -Destination (Join-Path $staging $composeFile) -Force
    }

    Write-Step "Upload to ${remote}:${RemoteRoot}"
    Invoke-DeployCommand "$scpBase -r `"$staging/backend`" `"$staging/new_frontend`" `"$staging/deploy`" `"$staging/docker-compose.prod.yml`" `"$staging/docker-compose.prod.vps.yml`" ${remote}:${RemoteRoot}/"

    Write-Step "Remove leaked backend/.env on server (must not override compose DB_*)"
    Invoke-DeployCommand "$sshBase `"rm -f ${RemoteRoot}/backend/.env`""

    if ($SkipBuild) {
        Write-Step "SkipBuild: containers not rebuilt"
    }
    else {
        $services = switch ($Target) {
            "backend" { "backend" }
            "frontend" { "frontend" }
            default { "backend frontend" }
        }
        Write-Step "docker compose up -d --build $services"
        $composeCmd = "cd $RemoteRoot && docker compose -f docker-compose.prod.yml -f docker-compose.prod.vps.yml up -d --build $services"
        Invoke-DeployCommand "$sshBase `"$composeCmd`""
    }

    if (-not $SkipBuild -and -not $DryRun) {
        Write-Step "Health check"
        Start-Sleep -Seconds 5
        Invoke-DeployCommand "$sshBase `"curl -sf http://127.0.0.1:9080/healthz/`""
        Write-Host ""
        Write-Host "Deploy OK: http://${SshHost}:9080/ (https://atome-farm.duckdns.org/accounts-stats/)" -ForegroundColor Green
    }
    elseif ($DryRun) {
        Write-Host "Dry run finished." -ForegroundColor Yellow
    }
}
finally {
    if (Test-Path $staging) {
        Remove-Item -Path $staging -Recurse -Force -ErrorAction SilentlyContinue
    }
}
