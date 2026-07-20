[CmdletBinding()]
param(
    [switch]$Gpu,
    [switch]$NoBrowser,
    [string]$WslDistribution = ""
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$LauncherRoot = Join-Path $env:LOCALAPPDATA "OpenShorts"
$LogPath = Join-Path $LauncherRoot "launcher.log"
$ExitCode = 0

New-Item -ItemType Directory -Force -Path $LauncherRoot | Out-Null
if ((Test-Path -LiteralPath $LogPath) -and (Get-Item -LiteralPath $LogPath).Length -gt 2MB) {
    Move-Item -LiteralPath $LogPath -Destination (Join-Path $LauncherRoot "launcher.previous.log") -Force
}

Start-Transcript -Path $LogPath -Append | Out-Null
try {
    Set-Location $ProjectRoot
    . (Join-Path $PSScriptRoot "windows_docker.ps1")

    Write-Host "OpenShorts launcher: $(Get-Date -Format o)"
    $AlreadyReady = (
        (Test-OpenShortsUrl -Url "http://localhost:5175/") -and
        (Test-OpenShortsUrl -Url "http://localhost:8000/openapi.json") -and
        (Test-OpenShortsUrl -Url "http://localhost:5175/api/jobs/history?limit=1")
    )
    if ($AlreadyReady) {
        Write-Host "OpenShorts laeuft bereits."
    } else {
        $Runtime = Get-OpenShortsDockerRuntime -ProjectRoot $ProjectRoot -WslDistribution $WslDistribution -StartIfNeeded
        Write-Host "Docker runtime: $($Runtime.Mode) $($Runtime.WslDistribution)"

        if (-not (Test-Path -LiteralPath (Join-Path $ProjectRoot ".env"))) {
            Copy-Item -LiteralPath (Join-Path $ProjectRoot ".env.example") -Destination (Join-Path $ProjectRoot ".env")
        }
        New-Item -ItemType Directory -Force -Path (Join-Path $ProjectRoot "output"), (Join-Path $ProjectRoot "output\longform_source_mount") | Out-Null

        $ComposeArguments = @("compose", "-f", "docker-compose.windows.yml")
        if ($Gpu) {
            $ComposeArguments += @("-f", "docker-compose.windows.gpu.yml")
        }
        $ComposeArguments += @("up", "-d", "backend", "frontend")
        Invoke-OpenShortsDocker -Runtime $Runtime -DockerArguments $ComposeArguments

        $BackendReady = $false
        for ($Attempt = 1; $Attempt -le 90; $Attempt++) {
            if (Test-OpenShortsUrl -Url "http://localhost:8000/openapi.json") {
                $BackendReady = $true
                break
            }
            Start-Sleep -Seconds 2
        }
        if (-not $BackendReady) {
            throw "Das Backend wurde nicht rechtzeitig erreichbar."
        }

        $FrontendReady = $false
        for ($Attempt = 1; $Attempt -le 90; $Attempt++) {
            if (Test-OpenShortsUrl -Url "http://localhost:5175/") {
                $FrontendReady = $true
                break
            }
            Start-Sleep -Seconds 2
        }
        if (-not $FrontendReady) {
            throw "Das Frontend wurde nicht rechtzeitig erreichbar."
        }

        $ProxyReady = $false
        for ($Attempt = 1; $Attempt -le 30; $Attempt++) {
            if (Test-OpenShortsUrl -Url "http://localhost:5175/api/jobs/history?limit=1") {
                $ProxyReady = $true
                break
            }
            Start-Sleep -Seconds 2
        }
        if (-not $ProxyReady) {
            throw "Der Dashboard-Proxy zum Backend antwortet nicht."
        }
    }

    if (-not $NoBrowser) {
        Start-Process "http://localhost:5175/#app"
    }
} catch {
    $ExitCode = 1
    Write-Error $_
} finally {
    Stop-Transcript | Out-Null
}

exit $ExitCode
