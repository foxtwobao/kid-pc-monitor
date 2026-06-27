from __future__ import annotations

import argparse
import hashlib
import shutil
import subprocess
import sys
from pathlib import Path


PROGRAM_DIR = Path(r"C:\Program Files\KidPCMonitor")
DATA_DIR = Path(r"C:\ProgramData\KidPCMonitor")
TOKEN_HASH_FILE = DATA_DIR / "uninstall.sha256"


def token_matches(token: str, token_file: Path | None = None) -> bool:
    token_file = token_file or TOKEN_HASH_FILE
    if not token_file.exists():
        return False
    expected = token_file.read_text(encoding="utf-8").strip()
    actual = hashlib.sha256(token.encode("utf-8")).hexdigest()
    return expected == actual


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--token", required=True)
    parser.add_argument("--preserve-logs", action="store_true")
    args = parser.parse_args()
    if not token_matches(args.token):
        raise SystemExit("Invalid uninstall token")
    service_script = PROGRAM_DIR / "src" / "windows_service.py"
    subprocess.run([sys.executable, str(service_script), "stop"], check=False)
    subprocess.run([sys.executable, str(service_script), "remove"], check=True)
    subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-Command",
            (
                'Remove-NetFirewallRule -DisplayName "Kid PC Monitor Agent" -ErrorAction SilentlyContinue; '
                'Remove-ItemProperty -Path "HKLM:\\Software\\Microsoft\\Windows\\CurrentVersion\\Run" '
                '-Name "KidPCMonitorHelper" -ErrorAction SilentlyContinue'
            ),
        ],
        check=True,
    )
    if not args.preserve_logs:
        shutil.rmtree(DATA_DIR, ignore_errors=True)
    shutil.rmtree(PROGRAM_DIR, ignore_errors=True)
    print("Kid PC Monitor service removed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
