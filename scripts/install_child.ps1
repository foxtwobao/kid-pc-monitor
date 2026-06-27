function Install-KidPCMonitorChild {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ParentUrl,

        [Parameter(Mandatory = $true)]
        [string]$PairingToken,

        [string]$RepoZipUrl = "https://github.com/foxtwobao/kid-pc-monitor/archive/refs/heads/main.zip"
    )

    $ErrorActionPreference = "Stop"

    $principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw "Please run this command from an Administrator PowerShell."
    }

    if ($ParentUrl -notmatch "^https?://") {
        $ParentUrl = "http://$ParentUrl"
    }
    $ParentUrl = $ParentUrl.TrimEnd("/")
    $parentUri = [Uri]$ParentUrl
    $parentHost = $parentUri.Host

    $python = (Get-Command python.exe -ErrorAction SilentlyContinue).Source
    if (-not $python) {
        throw "Python is required. Install Python 3.10+ first, then rerun the one-line command."
    }

    $workDir = Join-Path $env:TEMP ("kid-pc-monitor-" + [Guid]::NewGuid().ToString("N"))
    $zipPath = Join-Path $workDir "kid-pc-monitor.zip"
    New-Item -ItemType Directory -Force -Path $workDir | Out-Null

    Write-Host "Downloading Kid PC Monitor..."
    Invoke-WebRequest -UseBasicParsing -Uri $RepoZipUrl -OutFile $zipPath
    Expand-Archive -Path $zipPath -DestinationPath $workDir -Force
    $repoDir = Get-ChildItem -Path $workDir -Directory | Select-Object -First 1
    if (-not $repoDir) {
        throw "Could not find extracted repository directory."
    }

    Write-Host "Installing Python dependencies..."
    & $python -m pip install -r (Join-Path $repoDir.FullName "requirements.txt")

    Write-Host "Installing child-side Windows service..."
    & $python (Join-Path $repoDir.FullName "scripts\install_service.py") --parent-ip $parentHost --uninstall-token $PairingToken

    $secretPath = "C:\ProgramData\KidPCMonitor\agent.secret"
    $secret = (Get-Content $secretPath -Raw).Trim()
    $childIp = $null
    $ipConfig = Get-NetIPConfiguration |
        Where-Object { $_.IPv4DefaultGateway -and $_.IPv4Address } |
        Select-Object -First 1
    if ($ipConfig) {
        $childIp = $ipConfig.IPv4Address.IPAddress
    }

    $body = @{
        token = $PairingToken
        hostname = $env:COMPUTERNAME
        secret = $secret
    }
    if ($childIp) {
        $body.ip = $childIp
    }

    Write-Host "Pairing with parent panel..."
    Invoke-RestMethod `
        -Method Post `
        -Uri ($ParentUrl + "/api/pair") `
        -ContentType "application/json" `
        -Body ($body | ConvertTo-Json -Depth 5) | Out-Null

    Write-Host ""
    Write-Host "Kid PC Monitor child service installed and paired."
    Write-Host "Service: KidPCMonitorService"
    Write-Host "Parent:  $ParentUrl"
}
