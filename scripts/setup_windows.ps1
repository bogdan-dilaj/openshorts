[CmdletBinding()]
param(
    [switch]$Gpu,
    [switch]$NoBuild,
    [switch]$NoBrowser
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot

function Assert-LastExitCode([string]$Message) {
    if ($LASTEXITCODE -ne 0) {
        throw "$Message (exit code $LASTEXITCODE)"
    }
}

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw "Docker wurde nicht gefunden. Docker Desktop mit WSL-2-Backend installieren und danach erneut ausführen."
}

& docker compose version | Out-Host
Assert-LastExitCode "Docker Compose ist nicht verfügbar"
& docker info *> $null
Assert-LastExitCode "Docker Desktop läuft nicht"

if ($Gpu -and -not (Get-Command nvidia-smi -ErrorAction SilentlyContinue)) {
    Write-Warning "nvidia-smi wurde nicht gefunden. GPU-Start kann ohne passenden NVIDIA-Treiber fehlschlagen."
}

if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Host "Neue .env aus .env.example erstellt."
}

New-Item -ItemType Directory -Force -Path "output", "output/longform_source_mount" | Out-Null

$ComposeArgs = @("compose", "-f", "docker-compose.windows.yml")
if ($Gpu) {
    $ComposeArgs += @("-f", "docker-compose.windows.gpu.yml")
}

& docker @ComposeArgs config --quiet
Assert-LastExitCode "Die Windows-Compose-Konfiguration ist ungültig"

$UpArgs = @("up", "-d")
if (-not $NoBuild) {
    $UpArgs += "--build"
}
$UpArgs += @("backend", "frontend")
& docker @ComposeArgs @UpArgs
Assert-LastExitCode "OpenShorts konnte nicht gestartet werden"

$BackendReady = $false
for ($Attempt = 1; $Attempt -le 60; $Attempt++) {
    try {
        $Response = Invoke-WebRequest -UseBasicParsing -Uri "http://localhost:8000/openapi.json" -TimeoutSec 3
        if ($Response.StatusCode -eq 200) {
            $BackendReady = $true
            break
        }
    } catch {
        Start-Sleep -Seconds 2
    }
}

if (-not $BackendReady) {
    & docker @ComposeArgs ps
    & docker @ComposeArgs logs --tail 80 backend
    throw "Backend wurde nicht rechtzeitig erreichbar. Die letzten Logs stehen oben."
}

$FrontendReady = $false
for ($Attempt = 1; $Attempt -le 30; $Attempt++) {
    try {
        $Response = Invoke-WebRequest -UseBasicParsing -Uri "http://localhost:5175" -TimeoutSec 3
        if ($Response.StatusCode -eq 200) {
            $FrontendReady = $true
            break
        }
    } catch {
        Start-Sleep -Seconds 2
    }
}

if (-not $FrontendReady) {
    & docker @ComposeArgs logs --tail 80 frontend
    throw "Frontend wurde nicht rechtzeitig erreichbar. Die letzten Logs stehen oben."
}

Write-Host "OpenShorts läuft unter http://localhost:5175"
Write-Host "Import: Einstellungen -> Geräte-Sync -> Einstellungen importieren"
Write-Host "Projekte und Medien werden durch den Settings-Import nicht übernommen."

if (-not $NoBrowser) {
    Start-Process "http://localhost:5175"
}
