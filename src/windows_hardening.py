from __future__ import annotations

import subprocess
from pathlib import Path


SERVICE_NAME = "KidPCMonitorService"
HELPER_TASK_NAME = "KidPCMonitorHelper"
PROGRAM_DIR = Path(r"C:\Program Files\KidPCMonitor")
DATA_DIR = Path(r"C:\ProgramData\KidPCMonitor")
POLICY_PATH = DATA_DIR / "policy.json"
STATE_PATH = DATA_DIR / "state.json"
SECRET_PATH = DATA_DIR / "agent.secret"
HELPER_COMMAND_PATH = DATA_DIR / "helper_commands.jsonl"
EVENT_LOG_PATH = DATA_DIR / "events.jsonl"
UNINSTALL_HASH_PATH = DATA_DIR / "uninstall.sha256"


def run_powershell(script: str) -> None:
    subprocess.run(
        ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
        check=True,
    )


def acl_script() -> str:
    return rf"""
New-Item -ItemType Directory -Force -Path "{PROGRAM_DIR}" | Out-Null
New-Item -ItemType Directory -Force -Path "{DATA_DIR}" | Out-Null
icacls "{PROGRAM_DIR}" /inheritance:r /grant:r "SYSTEM:(OI)(CI)F" "Administrators:(OI)(CI)F" "Users:(OI)(CI)RX" | Out-Null
icacls "{DATA_DIR}" /inheritance:r /grant:r "SYSTEM:(OI)(CI)F" "Administrators:(OI)(CI)F" "Users:(OI)(CI)RX" | Out-Null
"""


def apply_acls() -> None:
    run_powershell(acl_script())


def firewall_script(parent_ip: str | None) -> str:
    remote_filter = f'-RemoteAddress "{parent_ip}"' if parent_ip else ""
    return rf"""
Remove-NetFirewallRule -DisplayName "Kid PC Monitor Agent" -ErrorAction SilentlyContinue
New-NetFirewallRule -DisplayName "Kid PC Monitor Agent" -Direction Inbound -Protocol TCP -LocalPort 9999 {remote_filter} -Profile Any -Action Allow -Enabled True | Out-Null
"""


def configure_firewall(parent_ip: str | None) -> None:
    run_powershell(firewall_script(parent_ip))


def service_recovery_command() -> list[str]:
    return [
        "sc.exe",
        "failure",
        SERVICE_NAME,
        "reset=",
        "86400",
        "actions=",
        "restart/60000/restart/60000/restart/60000",
    ]


def configure_service_recovery() -> None:
    subprocess.run(service_recovery_command(), check=True)


def helper_run_command(python_exe: str = "pythonw.exe") -> str:
    helper = PROGRAM_DIR / "src" / "helper.py"
    return f'"{python_exe}" "{helper}" --command-file "{HELPER_COMMAND_PATH}"'


def register_helper_run_key(python_exe: str = "pythonw.exe") -> None:
    command = helper_run_command(python_exe)
    script = rf"""
New-Item -Path "HKLM:\Software\Microsoft\Windows\CurrentVersion\Run" -Force | Out-Null
Set-ItemProperty -Path "HKLM:\Software\Microsoft\Windows\CurrentVersion\Run" -Name "KidPCMonitorHelper" -Value '{command}'
"""
    run_powershell(script)
