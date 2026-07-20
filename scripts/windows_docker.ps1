Set-StrictMode -Version Latest

function Test-OpenShortsWindowsDocker {
    param([Parameter(Mandatory = $true)][string]$DockerPath)

    & $DockerPath info *> $null
    return $LASTEXITCODE -eq 0
}

function Get-OpenShortsWslDistributions {
    if (-not (Get-Command wsl.exe -ErrorAction SilentlyContinue)) {
        return @()
    }

    $Distributions = @(& wsl.exe --list --quiet 2>$null)
    return @(
        $Distributions |
            ForEach-Object { ($_ -replace "`0", "").Trim() } |
            Where-Object { $_ -and $_ -notmatch "^docker-desktop" }
    )
}

function Test-OpenShortsWslDocker {
    param([Parameter(Mandatory = $true)][string]$Distribution)

    & wsl.exe -d $Distribution -- docker info *> $null
    return $LASTEXITCODE -eq 0
}

function Start-OpenShortsDockerDesktop {
    param(
        [Parameter(Mandatory = $true)][string]$DockerPath,
        [int]$TimeoutSeconds = 180
    )

    $DesktopPath = Join-Path $env:ProgramFiles "Docker\Docker\Docker Desktop.exe"
    if (-not (Test-Path -LiteralPath $DesktopPath)) {
        return $false
    }

    if (-not (Get-Process -Name "Docker Desktop" -ErrorAction SilentlyContinue)) {
        Start-Process -FilePath $DesktopPath | Out-Null
    }

    $Deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    do {
        Start-Sleep -Seconds 3
        if (Test-OpenShortsWindowsDocker -DockerPath $DockerPath) {
            return $true
        }
    } while ((Get-Date) -lt $Deadline)

    return $false
}

function Start-OpenShortsWslDocker {
    param([Parameter(Mandatory = $true)][string]$Distribution)

    & wsl.exe -d $Distribution -u root -- sh -lc "systemctl start docker >/dev/null 2>&1 || service docker start >/dev/null 2>&1" *> $null
    if ($LASTEXITCODE -ne 0) {
        return $false
    }

    for ($Attempt = 1; $Attempt -le 30; $Attempt++) {
        if (Test-OpenShortsWslDocker -Distribution $Distribution) {
            return $true
        }
        Start-Sleep -Seconds 2
    }

    return $false
}

function Get-OpenShortsDockerRuntime {
    param(
        [Parameter(Mandatory = $true)][string]$ProjectRoot,
        [string]$WslDistribution = "",
        [switch]$StartIfNeeded
    )

    $DockerCommand = Get-Command docker -ErrorAction SilentlyContinue
    $DockerPath = if ($DockerCommand) { $DockerCommand.Source } else { "" }
    if (-not $DockerPath) {
        $BundledDockerPath = Join-Path $env:ProgramFiles "Docker\Docker\resources\bin\docker.exe"
        if (Test-Path -LiteralPath $BundledDockerPath) {
            $DockerPath = $BundledDockerPath
        }
    }

    if ($DockerPath) {
        $WindowsReady = Test-OpenShortsWindowsDocker -DockerPath $DockerPath
        if (-not $WindowsReady -and $StartIfNeeded) {
            $WindowsReady = Start-OpenShortsDockerDesktop -DockerPath $DockerPath
        }
        if ($WindowsReady) {
            return [PSCustomObject]@{
                Mode = "windows"
                DockerPath = $DockerPath
                WslDistribution = ""
                ProjectPath = $ProjectRoot
            }
        }
    }

    $Candidates = @()
    if ($WslDistribution) {
        $Candidates += $WslDistribution
    }
    $Candidates += Get-OpenShortsWslDistributions
    $Candidates = @($Candidates | Select-Object -Unique)

    foreach ($Distribution in $Candidates) {
        $WslReady = Test-OpenShortsWslDocker -Distribution $Distribution
        if (-not $WslReady -and $StartIfNeeded) {
            $WslReady = Start-OpenShortsWslDocker -Distribution $Distribution
        }
        if (-not $WslReady) {
            continue
        }

        $PortableProjectRoot = $ProjectRoot.Replace("\", "/")
        $WslProjectPaths = @(& wsl.exe -d $Distribution -- wslpath -a $PortableProjectRoot 2>$null)
        if ($WslProjectPaths.Count -eq 0 -or -not $WslProjectPaths[0]) {
            continue
        }
        $WslProjectPath = $WslProjectPaths[0]

        return [PSCustomObject]@{
            Mode = "wsl"
            DockerPath = "docker"
            WslDistribution = $Distribution
            ProjectPath = $WslProjectPath.Trim()
        }
    }

    throw "Docker ist nicht erreichbar. Docker Desktop starten oder Docker in einer WSL-Distribution installieren."
}

function Invoke-OpenShortsDocker {
    param(
        [Parameter(Mandatory = $true)]$Runtime,
        [Parameter(Mandatory = $true)][string[]]$DockerArguments,
        [switch]$AllowFailure
    )

    if ($Runtime.Mode -eq "windows") {
        & $Runtime.DockerPath @DockerArguments
    } else {
        & wsl.exe -d $Runtime.WslDistribution --cd $Runtime.ProjectPath -- docker @DockerArguments
    }

    $ExitCode = $LASTEXITCODE
    if ($ExitCode -ne 0 -and -not $AllowFailure) {
        throw "Docker-Befehl fehlgeschlagen (Exit-Code $ExitCode): docker $($DockerArguments -join ' ')"
    }
}

function Test-OpenShortsUrl {
    param(
        [Parameter(Mandatory = $true)][string]$Url,
        [int]$TimeoutSeconds = 3
    )

    $Response = $null
    try {
        $Request = [System.Net.HttpWebRequest]::Create($Url)
        $Request.Method = "GET"
        $Request.Proxy = $null
        $Request.Accept = "text/html,application/json,*/*"
        $Request.UserAgent = "OpenShorts-Healthcheck"
        $Request.Timeout = $TimeoutSeconds * 1000
        $Request.ReadWriteTimeout = $TimeoutSeconds * 1000
        $Response = $Request.GetResponse()
        return [int]$Response.StatusCode -eq 200
    } catch {
        return $false
    } finally {
        if ($null -ne $Response) {
            $Response.Dispose()
        }
    }
}
