function Get-KidPCMonitorShortUserName {
    param([string]$UserName)
    if (-not $UserName) {
        return ""
    }
    return ($UserName -split "\\")[-1].Trim()
}

function Invoke-KidPCMonitorNativeCommand {
    param(
        [Parameter(Mandatory = $true)]
        [string]$FailureMessage,

        [Parameter(Mandatory = $true)]
        [scriptblock]$Command
    )

    & $Command
    if ($LASTEXITCODE -ne 0) {
        throw "$FailureMessage Exit code: $LASTEXITCODE"
    }
}

function Test-KidPCMonitorPython {
    param([string]$PythonPath)
    if (-not $PythonPath) {
        return $false
    }
    try {
        & $PythonPath -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)" *> $null
        return $LASTEXITCODE -eq 0
    } catch {
        return $false
    }
}

function Install-KidPCMonitorPython {
    param(
        [string]$InstallerUrl = "https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe"
    )

    $installerPath = Join-Path $env:TEMP "kid-pc-monitor-python-installer.exe"
    Write-Host "Python 3.10+ was not found. Installing Python 3.12..."
    Invoke-WebRequest -UseBasicParsing -Uri $InstallerUrl -OutFile $installerPath
    Invoke-KidPCMonitorNativeCommand -FailureMessage "Python installer failed." -Command {
        & $installerPath /quiet InstallAllUsers=1 PrependPath=1 Include_pip=1 Include_test=0
    }
}

function Get-KidPCMonitorPython {
    $candidates = @()
    $command = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($command) {
        $candidates += $command.Source
    }
    $candidates += @(
        "$env:ProgramFiles\Python312\python.exe",
        "$env:ProgramFiles\Python311\python.exe",
        "$env:ProgramFiles\Python310\python.exe",
        "${env:LocalAppData}\Programs\Python\Python312\python.exe",
        "${env:LocalAppData}\Programs\Python\Python311\python.exe",
        "${env:LocalAppData}\Programs\Python\Python310\python.exe"
    )

    foreach ($candidate in ($candidates | Where-Object { $_ } | Select-Object -Unique)) {
        if (Test-KidPCMonitorPython $candidate) {
            return $candidate
        }
    }

    Install-KidPCMonitorPython

    foreach ($candidate in ($candidates | Where-Object { $_ } | Select-Object -Unique)) {
        if (Test-KidPCMonitorPython $candidate) {
            return $candidate
        }
    }

    $refreshed = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($refreshed -and (Test-KidPCMonitorPython $refreshed.Source)) {
        return $refreshed.Source
    }

    throw "Python 3.10+ was installed, but python.exe could not be found. Open a new Administrator PowerShell and rerun the one-line command."
}

function Test-KidPCMonitorLocalAdmin {
    param([string]$UserName)
    $shortName = Get-KidPCMonitorShortUserName $UserName
    if (-not $shortName) {
        return $false
    }
    try {
        $adminGroup = Get-LocalGroup -ErrorAction Stop |
            Where-Object { $_.SID -eq "S-1-5-32-544" } |
            Select-Object -First 1
        if (-not $adminGroup) {
            return $false
        }
        $adminNames = Get-LocalGroupMember -Group $adminGroup.Name -ErrorAction Stop |
            ForEach-Object { Get-KidPCMonitorShortUserName $_.Name }
        return $adminNames -contains $shortName
    } catch {
        return $false
    }
}

function Get-KidPCMonitorSelectableUsers {
    $systemUsers = @("Administrator", "DefaultAccount", "Guest", "WDAGUtilityAccount")
    try {
        return @(Get-LocalUser |
            Where-Object { $_.Enabled -and $_.Name -notin $systemUsers } |
            Sort-Object -Property Name |
            ForEach-Object {
                [PSCustomObject]@{
                    Name = $_.Name
                    IsAdmin = Test-KidPCMonitorLocalAdmin $_.Name
                    LastLogon = $_.LastLogon
                }
            })
    } catch {
        return @()
    }
}

function Get-KidPCMonitorChildUser {
    param([string]$RequestedChildUser)

    if ($RequestedChildUser) {
        return Get-KidPCMonitorShortUserName $RequestedChildUser
    }

    $users = @(Get-KidPCMonitorSelectableUsers)
    if ($users.Count -eq 0) {
        $fallback = Get-KidPCMonitorShortUserName ([Security.Principal.WindowsIdentity]::GetCurrent().Name)
        Write-Host "Could not list local users. Falling back to current user: $fallback"
        return $fallback
    }

    Write-Host ""
    Write-Host "Select the Windows user to monitor:"
    for ($index = 0; $index -lt $users.Count; $index++) {
        $user = $users[$index]
        $suffix = ""
        if ($user.IsAdmin) {
            $suffix = " (admin)"
        }
        Write-Host ("  [{0}] {1}{2}" -f ($index + 1), $user.Name, $suffix)
    }

    while ($true) {
        $choice = Read-Host "Enter user number"
        $number = 0
        if ([int]::TryParse($choice, [ref]$number) -and $number -ge 1 -and $number -le $users.Count) {
            return $users[$number - 1].Name
        }
        Write-Host "Invalid selection. Enter a number from 1 to $($users.Count)."
    }
}

function Set-KidPCMonitorInitialPolicy {
    param([string]$ChildUser)

    if (-not $ChildUser) {
        return
    }

    $policyPath = "C:\ProgramData\KidPCMonitor\policy.json"
    if (Test-Path $policyPath) {
        $policy = Get-Content -Raw -Path $policyPath | ConvertFrom-Json
        if (-not ($policy.PSObject.Properties.Name -contains "policy_version")) {
            $policy | Add-Member -NotePropertyName "policy_version" -NotePropertyValue 0
        }
        if (-not ($policy.PSObject.Properties.Name -contains "updated_at")) {
            $policy | Add-Member -NotePropertyName "updated_at" -NotePropertyValue ""
        }
        if ($policy.PSObject.Properties.Name -contains "monitored_users") {
            $policy.PSObject.Properties.Remove("monitored_users")
        }
        $policy | Add-Member -NotePropertyName "monitored_users" -NotePropertyValue @($ChildUser)
        $policy.policy_version = [int]$policy.policy_version + 1
        $policy.updated_at = [DateTimeOffset]::Now.ToString("o")
    } else {
        $policy = [ordered]@{
            device_id = $env:COMPUTERNAME
            policy_version = 1
            daily_limit_minutes = $null
            bedtime_windows = @()
            monitored_users = @($ChildUser)
            exempt_users = @()
            warning_minutes = @(15, 5, 1)
            temporary_extensions = @{}
            parent_panel_allowed_ips = @()
            updated_at = [DateTimeOffset]::Now.ToString("o")
        }
    }
    $json = $policy | ConvertTo-Json -Depth 8
    [System.IO.File]::WriteAllText($policyPath, $json, [System.Text.UTF8Encoding]::new($false))
}

function Test-KidPCMonitorChildConnectivity {
    param([string]$ParentHost)

    $service = Get-Service -Name "KidPCMonitorService" -ErrorAction SilentlyContinue
    if (-not $service) {
        throw "KidPCMonitorService was not installed."
    }
    if ($service.Status -ne "Running") {
        Start-Service -Name "KidPCMonitorService" -ErrorAction SilentlyContinue
        $service.WaitForStatus("Running", [TimeSpan]::FromSeconds(30))
        $service = Get-Service -Name "KidPCMonitorService"
    }
    if ($service.Status -ne "Running") {
        throw "KidPCMonitorService is not running after installation."
    }

    $listener = Get-NetTCPConnection -LocalPort 9999 -State Listen -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if (-not $listener) {
        throw "KidPCMonitorService is running, but LocalPort 9999 is not listening."
    }

    $firewallRule = Get-NetFirewallRule -DisplayName "Kid PC Monitor Agent" -ErrorAction SilentlyContinue |
        Where-Object { $_.Enabled -eq "True" -and $_.Direction -eq "Inbound" -and $_.Action -eq "Allow" } |
        Select-Object -First 1
    if (-not $firewallRule) {
        throw "Windows Firewall rule 'Kid PC Monitor Agent' is missing or disabled."
    }

    $portFilter = $firewallRule | Get-NetFirewallPortFilter
    if (-not ($portFilter | Where-Object { $_.LocalPort -eq "9999" })) {
        throw "Windows Firewall rule exists, but does not allow LocalPort 9999."
    }

    $addressFilter = $firewallRule | Get-NetFirewallAddressFilter
    $remoteAddresses = @($addressFilter.RemoteAddress)
    if ($ParentHost -and $remoteAddresses -notcontains "Any" -and $remoteAddresses -notcontains $ParentHost) {
        throw "Windows Firewall rule exists, but RemoteAddress is '$($remoteAddresses -join ',')', not '$ParentHost'."
    }

    Write-Host "Child service is running, LocalPort 9999 is listening, and firewall allows parent host $ParentHost."
}

function Install-KidPCMonitorChild {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ParentUrl,

        [Parameter(Mandatory = $true)]
        [string]$PairingToken,

        [string]$ChildUser = "",

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

    $python = Get-KidPCMonitorPython

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
    Invoke-KidPCMonitorNativeCommand -FailureMessage "Python dependency installation failed." -Command {
        & $python -m pip install -r (Join-Path $repoDir.FullName "requirements.txt")
    }

    Write-Host "Installing child-side Windows service..."
    Invoke-KidPCMonitorNativeCommand -FailureMessage "Child service installer failed." -Command {
        & $python (Join-Path $repoDir.FullName "scripts\install_service.py") --parent-ip $parentHost --uninstall-token $PairingToken
    }
    Test-KidPCMonitorChildConnectivity -ParentHost $parentHost

    $selectedChildUser = Get-KidPCMonitorChildUser -RequestedChildUser $ChildUser
    if ($selectedChildUser) {
        Write-Host "Monitoring Windows user: $selectedChildUser"
        Set-KidPCMonitorInitialPolicy -ChildUser $selectedChildUser
    } else {
        Write-Host "No specific child user detected; service will monitor all non-exempt users."
    }

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
        monitored_users = @()
    }
    if ($selectedChildUser) {
        $body.monitored_users = @($selectedChildUser)
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
    if ($selectedChildUser) {
        Write-Host "User:    $selectedChildUser"
    }
}
