#Requires -Version 5.1
<#
.SYNOPSIS
  Sync secrets and browser profile to Mobile Farm (10.20.87.230).

.EXAMPLE
  .\scripts\sync-mobilefarm-secrets.ps1
  .\scripts\sync-mobilefarm-secrets.ps1 -SkipBrowserProfile
#>
[CmdletBinding()]
param(
    [string]$SshHost = "10.20.87.230",
    [string]$SshUser = "atom",
    [string]$IdentityFile = "",
    [string]$RemoteRoot = "/home/atom/dashboard",
    [string]$LocalEnv = "",
    [string]$LocalWorkerEnv = "",
    [string]$LocalBrowserProfile = "",
    [switch]$SkipBrowserProfile,
    [switch]$DryRun
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Write-Step([string]$Message) {
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Resolve-IdentityFile([string]$Preferred) {
    if ($Preferred -and (Test-Path $Preferred)) { return $Preferred }
    foreach ($c in @(
            "$env:USERPROFILE\.ssh\id_ed25519",
            "$env:USERPROFILE\.ssh\id_rsa"
        )) {
        if (Test-Path $c) { return $c }
    }
    throw "SSH key not found"
}

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$IdentityFile = Resolve-IdentityFile $IdentityFile
$remote = "${SshUser}@${SshHost}"
$ssh = "ssh -i `"$IdentityFile`" -o BatchMode=yes -o ConnectTimeout=15 $remote"
$scp = "scp -i `"$IdentityFile`" -o BatchMode=yes"

if (-not $LocalWorkerEnv) { $LocalWorkerEnv = Join-Path $repoRoot "backend\config\worker_accounts.env" }
if (-not $LocalEnv) {
    foreach ($candidate in @(
            (Join-Path $repoRoot ".env"),
            (Join-Path $repoRoot "backend\.env")
        )) {
        if (Test-Path $candidate) { $LocalEnv = $candidate; break }
    }
}
if (-not $LocalEnv -or -not (Test-Path $LocalEnv)) {
    throw "Missing .env (repo root or backend/.env). Fill in API keys first."
}

Write-Step "Target: ${remote}:${RemoteRoot}"

if (Test-Path $LocalWorkerEnv) {
    Write-Step "Upload worker_accounts.env"
    if (-not $DryRun) {
        Invoke-Expression "$scp `"$LocalWorkerEnv`" ${remote}:${RemoteRoot}/backend/config/worker_accounts.env"
    }
}
else {
    Write-Warning "No $LocalWorkerEnv - skip"
}

Write-Step "Merge .env (local secrets, server hosts/DB)"
$tmp = Join-Path $env:TEMP ("dashboard-env-merge-{0}" -f [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $tmp -Force | Out-Null
try {
    $merged = Join-Path $tmp ".env.merged"
    if (-not $DryRun) {
        Invoke-Expression "$scp ${remote}:${RemoteRoot}/.env `"$tmp\server.env`""
        python (Join-Path $repoRoot "scripts\merge_mobilefarm_env.py") `
            --local $LocalEnv `
            --server (Join-Path $tmp "server.env") `
            --out $merged
        Invoke-Expression "$scp `"$merged`" ${remote}:${RemoteRoot}/.env"
    }
}
finally {
    Remove-Item -Path $tmp -Recurse -Force -ErrorAction SilentlyContinue
}

foreach ($pair in @(
        @{ Local = "backend\instagram.session"; Remote = "backend/instagram.session" }
        @{ Local = "backend\telegram.session"; Remote = "backend/telegram.session" }
        @{ Local = "backend\tiktok_state.json"; Remote = "backend/tiktok_state.json" }
    )) {
    $src = Join-Path $repoRoot $pair.Local
    if (Test-Path $src) {
        Write-Step "Upload $($pair.Local)"
        if (-not $DryRun) {
            Invoke-Expression "$scp `"$src`" ${remote}:${RemoteRoot}/$($pair.Remote)"
        }
    }
}

if (-not $SkipBrowserProfile) {
    if (-not $LocalBrowserProfile) {
        foreach ($c in @(
                (Join-Path $env:LOCALAPPDATA "TikStatsChromeProfile"),
                (Join-Path $repoRoot "backend\.browser-profile")
            )) {
            if ($c -and (Test-Path $c)) { $LocalBrowserProfile = $c; break }
        }
    }
    if ($LocalBrowserProfile -and (Test-Path $LocalBrowserProfile)) {
        Write-Step "Browser profile to Docker volume: $LocalBrowserProfile"
        $archive = Join-Path $env:TEMP ("browser-profile-{0}.tar.gz" -f [guid]::NewGuid().ToString("N"))
        if (-not $DryRun) {
            tar -czf $archive -C $LocalBrowserProfile .
            Invoke-Expression "$scp `"$archive`" ${remote}:/tmp/browser-profile-sync.tar.gz"
            $importCmd = "cd $RemoteRoot; docker compose -f docker-compose.prod.yml -f docker-compose.prod.mobilefarm.yml up -d backend 2>/dev/null; docker run --rm -v dashboard_browser_profile:/data -v /tmp/browser-profile-sync.tar.gz:/in.tar.gz:ro alpine sh -c 'cd /data && tar xzf /in.tar.gz && chown -R 1000:1000 /data 2>/dev/null || true'; rm -f /tmp/browser-profile-sync.tar.gz"
            Invoke-Expression "$ssh `"$importCmd`""
            Remove-Item $archive -Force -ErrorAction SilentlyContinue
        }
    }
    else {
        Write-Warning "Browser profile not found under backend\.browser-profile"
    }
}

Write-Step "Restart backend"
if (-not $DryRun) {
    $restart = "cd $RemoteRoot; if groups | grep -qw docker; then docker compose -f docker-compose.prod.yml -f docker-compose.prod.mobilefarm.yml up -d backend; else sudo docker compose -f docker-compose.prod.yml -f docker-compose.prod.mobilefarm.yml up -d backend; fi"
    Invoke-Expression "$ssh `"$restart`""
    Start-Sleep -Seconds 6
    $copySessions = @()
    if (Test-Path (Join-Path $repoRoot "backend\instagram.session")) {
        $copySessions += "docker cp ${RemoteRoot}/backend/instagram.session dashboard-backend:/app/instagram.session"
    }
    if (Test-Path (Join-Path $repoRoot "backend\tiktok_state.json")) {
        $copySessions += "docker cp ${RemoteRoot}/backend/tiktok_state.json dashboard-backend:/app/.browser-profile/tiktok_state.json"
    }
    if ($copySessions.Count -gt 0) {
        Write-Step "Copy session files into container"
        Invoke-Expression "$ssh `"$($copySessions -join '; ')`""
    }
    Invoke-Expression "$ssh 'docker exec dashboard-backend sh -c ""test -n \`$YOUTUBE_API_KEY && echo YOUTUBE:ok || echo YOUTUBE:empty; test -n \`$LINKS_API_TOKEN && echo LINKS:ok || echo LINKS:empty; test -f /app/.browser-profile/tiktok_state.json && echo tiktok:ok || echo tiktok:missing""'"
}

Write-Host ""
Write-Host "Done: http://${SshHost}:9080/" -ForegroundColor Green
