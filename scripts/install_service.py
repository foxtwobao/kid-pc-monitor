from __future__ import annotations

import argparse
import hashlib
import secrets
import shutil
import subprocess
import sys
import time
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.windows_hardening import (
    DATA_DIR,
    PROGRAM_DIR,
    SECRET_PATH,
    SERVICE_NAME,
    UNINSTALL_HASH_PATH,
    apply_acls,
    configure_firewall,
    configure_service_recovery,
    register_helper_run_key,
)


ROOT = Path(__file__).resolve().parents[1]


def ensure_pywin32_available() -> None:
    try:
        import win32serviceutil  # noqa: F401
    except ImportError as exc:
        raise SystemExit(
            "pywin32 is required to install KidPCMonitorService. "
            "Run: python -m pip install pywin32"
        ) from exc


def service_exists() -> bool:
    result = subprocess.run(["sc.exe", "query", SERVICE_NAME], check=False, capture_output=True, text=True)
    return result.returncode == 0


def service_state() -> str | None:
    result = subprocess.run(["sc.exe", "query", SERVICE_NAME], check=False, capture_output=True, text=True)
    if result.returncode != 0:
        return None
    for line in result.stdout.splitlines():
        if "STATE" in line and ":" in line:
            parts = line.split()
            return parts[-1] if parts else None
    return None


def wait_for_service_stopped(timeout_seconds: int = 30) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        state = service_state()
        if state in (None, "STOPPED"):
            return
        time.sleep(1)
    raise RuntimeError(f"{SERVICE_NAME} did not stop within {timeout_seconds} seconds.")


def stop_helper_processes() -> None:
    script = rf"""
Get-CimInstance Win32_Process |
    Where-Object {{ $_.CommandLine -like "*KidPCMonitor*helper.py*" }} |
    ForEach-Object {{ Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }}
"""
    subprocess.run(
        ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
        check=False,
    )


def stop_existing_runtime() -> None:
    if service_exists():
        subprocess.run(["sc.exe", "stop", SERVICE_NAME], check=False, capture_output=True, text=True)
        wait_for_service_stopped()
    stop_helper_processes()


def copy_agent_files() -> None:
    PROGRAM_DIR.mkdir(parents=True, exist_ok=True)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    for item in ["src", "scripts", "requirements.txt"]:
        source = ROOT / item
        target = PROGRAM_DIR / item
        if source.is_dir():
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(source, target)
        else:
            shutil.copy2(source, target)


def write_secret() -> None:
    if not SECRET_PATH.exists():
        SECRET_PATH.write_text(secrets.token_hex(32), encoding="utf-8")


def write_uninstall_hash(token: str) -> None:
    UNINSTALL_HASH_PATH.write_text(hashlib.sha256(token.encode("utf-8")).hexdigest(), encoding="utf-8")


def default_pythonw() -> str:
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    if pythonw.exists():
        return str(pythonw)
    return sys.executable


def install_service() -> None:
    service_script = PROGRAM_DIR / "src" / "windows_service.py"
    action = "update" if service_exists() else "install"
    subprocess.run([sys.executable, str(service_script), "--startup", "auto", action], check=True)
    configure_service_recovery()
    subprocess.run([sys.executable, str(service_script), "start"], check=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--parent-ip", default=None)
    parser.add_argument("--uninstall-token", required=True)
    parser.add_argument("--pythonw", default=None)
    args = parser.parse_args()
    ensure_pywin32_available()
    stop_existing_runtime()
    copy_agent_files()
    write_secret()
    write_uninstall_hash(args.uninstall_token)
    apply_acls()
    configure_firewall(args.parent_ip)
    register_helper_run_key(args.pythonw or default_pythonw())
    install_service()
    print("Kid PC Monitor service installed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
