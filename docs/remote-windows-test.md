# Remote Windows Test Checklist

Target: `192.168.10.251`

Do not store passwords in this file, command history, screenshots, logs, or commits.

## Current Probe

From the development machine:

- RDP `3389` is open.
- WinRM `5985/5986` is closed.
- SSH `22` is closed.
- SMB `445` is closed.
- Agent `9999` is closed before installation.
- ICMP ping may be blocked; this is not a blocker.

## Prerequisites

- Windows 10/11 test machine is reachable.
- Parent/admin account is available for installation.
- Child test account is a standard Windows user.
- Python 3.10+ is installed and available on PATH.
- RDP remains available as manual fallback.
- WinRM 5985 or OpenSSH is enabled for automated remote testing.

## Preferred WinRM Setup

Run on the Windows test machine from an elevated PowerShell:

```powershell
Set-ExecutionPolicy RemoteSigned -Scope LocalMachine -Force
Enable-PSRemoting -Force
Set-Item WSMan:\localhost\Service\AllowUnencrypted $true
Set-Item WSMan:\localhost\Service\Auth\Basic $true
New-NetFirewallRule -DisplayName "WinRM 5985" -Direction Inbound -Protocol TCP -LocalPort 5985 -Action Allow
```

After this, from the development machine:

```bash
for p in 3389 5985 5986 22 445 135 9999; do timeout 2 bash -c "</dev/tcp/192.168.10.251/$p" >/dev/null 2>&1 && echo "$p open" || echo "$p closed"; done
```

Expected before agent install: `3389 open` and `5985 open`.

## Commands To Run On Windows As Administrator

```powershell
python --version
whoami
net user
sc.exe query KidPCMonitorService
netsh advfirewall firewall show rule name="Kid PC Monitor Agent"
```

## Install

Copy or clone the repository onto the Windows machine, then run from an elevated PowerShell:

```powershell
cd C:\Users\hulei\kid-pc-monitor
python -m pip install -r requirements.txt
python scripts\install_service.py --parent-ip 192.168.10.10 --uninstall-token "<temporary-token>"
sc.exe query KidPCMonitorService
netsh advfirewall firewall show rule name="Kid PC Monitor Agent"
Get-ItemProperty -Path "HKLM:\Software\Microsoft\Windows\CurrentVersion\Run" -Name "KidPCMonitorHelper"
```

Expected:

- `KidPCMonitorService` exists and is running.
- Firewall rule allows TCP `9999`, scoped to the parent IP when supplied.
- HKLM Run entry exists for `KidPCMonitorHelper`.
- `C:\ProgramData\KidPCMonitor\agent.secret` exists.

## Parent Panel Secret Setup

Read `C:\ProgramData\KidPCMonitor\agent.secret` on the child PC as administrator. On the parent machine, start the web panel with a JSON secret map:

```bash
export KID_PC_DEVICE_SECRETS='{"192.168.10.251":"<hex-secret>"}'
python -m src.web_panel
```

## Offline Enforcement Test

1. From the parent panel, apply a one-minute daily limit to `192.168.10.251`.
2. Confirm the child service acknowledges the policy version.
3. Disable network on the child PC.
4. Wait for the warning and lock behavior.
5. Re-enable network.
6. Confirm the service still runs and the local state file shows the accepted policy version.

Useful Windows commands:

```powershell
Get-Content C:\ProgramData\KidPCMonitor\policy.json
Get-Content C:\ProgramData\KidPCMonitor\state.json
Get-Content C:\ProgramData\KidPCMonitor\helper_commands.jsonl
```

## Anti-Tamper Test

From the standard child account:

```powershell
sc.exe stop KidPCMonitorService
Remove-Item "C:\Program Files\KidPCMonitor" -Recurse
Remove-Item "C:\ProgramData\KidPCMonitor\policy.json"
```

Expected:

- Service stop fails with access denied.
- Program directory removal fails with access denied.
- Policy file removal fails with access denied or does not disable service enforcement.

## Uninstall Test

From an elevated PowerShell:

```powershell
python scripts\uninstall_service.py --token "<temporary-token>" --preserve-logs
sc.exe query KidPCMonitorService
```

Expected:

- Service is removed.
- Firewall rule is removed.
- HKLM Run entry is removed.
- Logs are preserved when `--preserve-logs` is supplied.
