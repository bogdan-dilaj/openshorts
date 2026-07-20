[CmdletBinding()]
param(
    [switch]$Gpu,
    [switch]$NoBuild,
    [switch]$NoBrowser,
    [switch]$NoLauncher,
    [string]$WslDistribution = ""
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot

. (Join-Path $PSScriptRoot "windows_docker.ps1")

function Install-OpenShortsLauncher {
    param(
        [switch]$UseGpu,
        [string]$PreferredWslDistribution = ""
    )

    $LauncherRoot = Join-Path $env:LOCALAPPDATA "OpenShorts"
    $VbsPath = Join-Path $LauncherRoot "Start-OpenShorts.vbs"
    $StartScript = Join-Path $PSScriptRoot "start_windows.ps1"
    $PowerShellPath = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"
    $LogPath = Join-Path $LauncherRoot "launcher.log"

    New-Item -ItemType Directory -Force -Path $LauncherRoot | Out-Null

    $Command = '"' + $PowerShellPath + '" -NoProfile -ExecutionPolicy Bypass -File "' + $StartScript + '"'
    if ($UseGpu) {
        $Command += " -Gpu"
    }
    if ($PreferredWslDistribution) {
        $Command += ' -WslDistribution "' + $PreferredWslDistribution.Replace('"', '') + '"'
    }
    $VbsCommand = $Command.Replace('"', '""')
    $VbsLogPath = $LogPath.Replace('"', '""')

    $VbsContent = @"
Option Explicit

Dim shell, exitCode
Set shell = CreateObject("WScript.Shell")
exitCode = shell.Run("$VbsCommand", 0, True)

If exitCode <> 0 Then
    MsgBox "OpenShorts konnte nicht gestartet werden." & vbCrLf & vbCrLf & _
        "Diagnoseprotokoll: $VbsLogPath", vbCritical, "OpenShorts"
End If

WScript.Quit exitCode
"@
    Set-Content -LiteralPath $VbsPath -Value $VbsContent -Encoding ASCII

    $ShortcutTargets = @(
        (Join-Path ([Environment]::GetFolderPath("Desktop")) "OpenShorts.lnk"),
        (Join-Path ([Environment]::GetFolderPath("Programs")) "OpenShorts.lnk")
    )
    $Shell = New-Object -ComObject WScript.Shell
    foreach ($ShortcutPath in $ShortcutTargets) {
        $Shortcut = $Shell.CreateShortcut($ShortcutPath)
        $Shortcut.TargetPath = Join-Path $env:SystemRoot "System32\wscript.exe"
        $Shortcut.Arguments = '"' + $VbsPath + '"'
        $Shortcut.WorkingDirectory = $ProjectRoot
        $Shortcut.Description = "OpenShorts starten"
        $Shortcut.IconLocation = (Join-Path $env:SystemRoot "System32\shell32.dll") + ",220"
        $Shortcut.Save()
    }

    Write-Host "Desktop- und Startmenue-Verknuepfung wurden erstellt."
}

$Runtime = Get-OpenShortsDockerRuntime -ProjectRoot $ProjectRoot -WslDistribution $WslDistribution -StartIfNeeded
Write-Host "Docker runtime: $($Runtime.Mode) $($Runtime.WslDistribution)"

Invoke-OpenShortsDocker -Runtime $Runtime -DockerArguments @("compose", "version")

if (-not (Test-Path -LiteralPath ".env")) {
    Copy-Item -LiteralPath ".env.example" -Destination ".env"
    Write-Host "Neue .env aus .env.example erstellt."
}

New-Item -ItemType Directory -Force -Path "output", "output\longform_source_mount" | Out-Null

$ComposeFiles = @("compose", "-f", "docker-compose.windows.yml")
if ($Gpu) {
    $ComposeFiles += @("-f", "docker-compose.windows.gpu.yml")
}

Invoke-OpenShortsDocker -Runtime $Runtime -DockerArguments ($ComposeFiles + @("config", "--quiet"))

$UpArguments = $ComposeFiles + @("up", "-d")
if (-not $NoBuild) {
    $UpArguments += "--build"
}
$UpArguments += @("backend", "frontend")
Invoke-OpenShortsDocker -Runtime $Runtime -DockerArguments $UpArguments

$BackendReady = $false
for ($Attempt = 1; $Attempt -le 90; $Attempt++) {
    if (Test-OpenShortsUrl -Url "http://localhost:8000/openapi.json") {
        $BackendReady = $true
        break
    }
    Start-Sleep -Seconds 2
}
if (-not $BackendReady) {
    Invoke-OpenShortsDocker -Runtime $Runtime -DockerArguments ($ComposeFiles + @("ps")) -AllowFailure
    Invoke-OpenShortsDocker -Runtime $Runtime -DockerArguments ($ComposeFiles + @("logs", "--tail", "100", "backend")) -AllowFailure
    throw "Backend wurde nicht rechtzeitig erreichbar. Die letzten Logs stehen oben."
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
    Invoke-OpenShortsDocker -Runtime $Runtime -DockerArguments ($ComposeFiles + @("logs", "--tail", "100", "frontend")) -AllowFailure
    throw "Frontend wurde nicht rechtzeitig erreichbar. Die letzten Logs stehen oben."
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
    throw "Das Dashboard ist erreichbar, aber sein Backend-Proxy antwortet nicht."
}

if ($Gpu) {
    Invoke-OpenShortsDocker -Runtime $Runtime -DockerArguments @(
        "exec", "openshorts-backend", "nvidia-smi", "--query-gpu=name,memory.total,driver_version", "--format=csv,noheader"
    )
    Invoke-OpenShortsDocker -Runtime $Runtime -DockerArguments @(
        "exec", "openshorts-backend", "python", "-c", "import video_encoding; print('Video encoder:', video_encoding.selected_h264_encoder())"
    )
}

if (-not $NoLauncher) {
    $PreferredDistribution = if ($Runtime.Mode -eq "wsl") { $Runtime.WslDistribution } else { "" }
    Install-OpenShortsLauncher -UseGpu:$Gpu -PreferredWslDistribution $PreferredDistribution
}

Write-Host "OpenShorts laeuft unter http://localhost:5175"
Write-Host "Settings-Import: Einstellungen -> Geraete-Sync -> Einstellungen importieren"
Write-Host "Die Settings-Datei enthaelt Geheimnisse und darf nicht in Git gespeichert werden."

if (-not $NoBrowser) {
    Start-Process "http://localhost:5175/#app"
}
