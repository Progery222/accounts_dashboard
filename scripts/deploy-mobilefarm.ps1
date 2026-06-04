#Requires -Version 5.1
<#
.SYNOPSIS
  Деплой Accounts Stats на GPU-сервер Mobile Farm (10.20.87.230).

.DESCRIPTION
  Синхронизация backend + new_frontend + deploy, docker compose prod (без VPS overlay).
  Требуется SSH-ключ: один раз `ssh-copy-id atom@10.20.87.230`.

.EXAMPLE
  .\scripts\deploy-mobilefarm.ps1

.EXAMPLE
  .\scripts\deploy-mobilefarm.ps1 -IdentityFile "$env:USERPROFILE\.ssh\id_ed25519"

  Синхронизирует: backend/, new_frontend/, deploy/, scripts/*.sh и *.py (операционные).
  НЕ синхронизирует: .env, worker_accounts.env, Chrome-профиль, backend/media, БД.
  После деплоя для сессий и ключей: .\scripts\sync-mobilefarm-secrets.ps1
#>
[CmdletBinding()]
param(
    [string]$SshHost = "10.20.87.230",
    [string]$SshUser = "atom",
    [string]$IdentityFile = "",
    [string]$RemoteRoot = "/home/atom/dashboard",
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

function Resolve-IdentityFile([string]$Preferred) {
    if ($Preferred -and (Test-Path $Preferred)) {
        return $Preferred
    }
    foreach ($candidate in @(
            "$env:USERPROFILE\.ssh\id_ed25519",
            "$env:USERPROFILE\.ssh\id_atome",
            "$env:USERPROFILE\.ssh\id_rsa"
        )) {
        if (Test-Path $candidate) {
            return $candidate
        }
    }
    throw "SSH key not found. Run: ssh-copy-id ${SshUser}@${SshHost}"
}

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$staging = Join-Path $env:TEMP ("dashboard-mobilefarm-{0}" -f [guid]::NewGuid().ToString("N"))
$remote = "${SshUser}@${SshHost}"
$IdentityFile = Resolve-IdentityFile $IdentityFile
$sshBase = "ssh -i `"$IdentityFile`" -o BatchMode=yes -o ConnectTimeout=15 $remote"
$scpBase = "scp -i `"$IdentityFile`" -o BatchMode=yes"

# media заливается отдельно (scp/rsync); на сервере часто root/docker — ломает scp при полном деплое
$robocopyExcludeDirs = @(".venv", ".venv-gil", "__pycache__", "var", "staticfiles", "node_modules", "media")
$robocopyExcludeFiles = @(".env", "worker_accounts.env", "worker_subs.env", "*.pyc", "*.session")

try {
    Write-Step "Repository: $repoRoot"
    Write-Step "Target: ${remote}:${RemoteRoot} (key: $IdentityFile)"
    New-Item -ItemType Directory -Path $staging -Force | Out-Null

    $backendStage = Join-Path $staging "backend"
    $newFrontendStage = Join-Path $staging "new_frontend"
    $deployStage = Join-Path $staging "deploy"

    Write-Step "Copy backend/"
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

    $composeSrc = Join-Path $repoRoot "docker-compose.prod.yml"
    if (-not (Test-Path $composeSrc)) {
        throw "Missing $composeSrc"
    }
    Copy-Item -Path $composeSrc -Destination (Join-Path $staging "docker-compose.prod.yml") -Force
    $mobilefarmCompose = Join-Path $repoRoot "docker-compose.prod.mobilefarm.yml"
    if (-not (Test-Path $mobilefarmCompose)) {
        throw "Missing $mobilefarmCompose"
    }
    Copy-Item -Path $mobilefarmCompose -Destination (Join-Path $staging "docker-compose.prod.mobilefarm.yml") -Force
    Copy-Item -Path (Join-Path $repoRoot ".env.example") -Destination (Join-Path $staging ".env.example") -Force
    Copy-Item -Path (Join-Path $repoRoot "scripts\write_mobilefarm_env.py") -Destination (Join-Path $staging "write_mobilefarm_env.py") -Force

    # Операционные скрипты (не весь scripts/ — там сотни одноразовых patch-*.mjs).
    $scriptsStage = Join-Path $staging "scripts"
    New-Item -ItemType Directory -Path $scriptsStage -Force | Out-Null
    $scriptsSrc = Join-Path $repoRoot "scripts"
    Get-ChildItem -Path $scriptsSrc -File | Where-Object {
        $_.Extension -in @(".sh", ".py") -or $_.Name -eq "merge_mobilefarm_env.py"
    } | ForEach-Object {
        Copy-Item -Path $_.FullName -Destination (Join-Path $scriptsStage $_.Name) -Force
    }

    Write-Step "Ensure remote directory"
    Invoke-DeployCommand "$sshBase `"mkdir -p ${RemoteRoot}`""

    Write-Step "Upload"
    Invoke-DeployCommand "$scpBase -r `"$staging/backend`" `"$staging/new_frontend`" `"$staging/deploy`" `"$staging/scripts`" `"$staging/docker-compose.prod.yml`" `"$staging/docker-compose.prod.mobilefarm.yml`" `"$staging/.env.example`" `"$staging/write_mobilefarm_env.py`" ${remote}:${RemoteRoot}/"

    Write-Step "Remove leaked backend/.env on server"
    Invoke-DeployCommand "$sshBase `"rm -f ${RemoteRoot}/backend/.env`""

    Write-Step "Create .env if missing"
    $envCmd = @"
cd ${RemoteRoot} && if [ ! -f .env ]; then python3 write_mobilefarm_env.py; else echo '.env exists, skip'; fi
"@
    Invoke-DeployCommand "$sshBase `"$envCmd`""

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
        # atom часто ещё не в группе docker после apt install (нужен re-login).
        $gitCommit = ""
        $gitDate = ""
        try {
            Push-Location $repoRoot
            $gitCommit = (git rev-parse HEAD 2>$null).Trim()
            $gitDate = (git log -1 --format="%ci" 2>$null).Trim()
        }
        finally {
            Pop-Location
        }
        if (-not $gitCommit) { $gitCommit = "unknown" }
        if (-not $gitDate) { $gitDate = "unknown" }
        $composeCmd = @"
cd $RemoteRoot && export GIT_COMMIT='$gitCommit' GIT_COMMIT_DATE='$gitDate' && if groups | grep -qw docker; then
  docker compose -f docker-compose.prod.yml -f docker-compose.prod.mobilefarm.yml up -d --build $services
else
  sudo docker compose -f docker-compose.prod.yml -f docker-compose.prod.mobilefarm.yml up -d --build $services
fi
"@
        Invoke-DeployCommand "$sshBase `"$composeCmd`""
    }

    if (-not $DryRun) {
        Write-Step "chmod scripts/*.sh on server"
        Invoke-DeployCommand "$sshBase `"chmod +x ${RemoteRoot}/scripts/*.sh 2>/dev/null; ln -sf ${RemoteRoot}/scripts/enable-mobilefarm-headed-browser.sh ${RemoteRoot}/enable-mobilefarm-headed-browser.sh 2>/dev/null || true`""
    }

    if (-not $SkipBuild -and -not $DryRun) {
        Write-Step "Health check"
        Start-Sleep -Seconds 8
        Invoke-DeployCommand "$sshBase `"curl -sf http://127.0.0.1:9080/healthz/`""
        Write-Host ""
        Write-Host "Deploy OK: http://${SshHost}:9080/" -ForegroundColor Green
        Write-Host "На сервере (SSH): bash ~/dashboard/scripts/enable-mobilefarm-xvfb.sh" -ForegroundColor DarkGray
        Write-Host "Окна на RDP: ~/dashboard/scripts/enable-mobilefarm-headed-browser.sh" -ForegroundColor DarkGray
        Write-Host "Логи на сервере: bash ~/dashboard/scripts/setup-mobilefarm-log-retention.sh" -ForegroundColor DarkGray
        Write-Host "Секреты/cookies с Windows: .\scripts\sync-mobilefarm-secrets.ps1" -ForegroundColor DarkGray
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
