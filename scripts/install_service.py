from __future__ import annotations

import argparse
import hashlib
import secrets
import shutil
import subprocess
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.windows_hardening import (
    DATA_DIR,
    PROGRAM_DIR,
    SECRET_PATH,
    UNINSTALL_HASH_PATH,
    apply_acls,
    configure_firewall,
    configure_service_recovery,
    register_helper_run_key,
)


ROOT = Path(__file__).resolve().parents[1]


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


def install_service() -> None:
    service_script = PROGRAM_DIR / "src" / "windows_service.py"
    subprocess.run([sys.executable, str(service_script), "--startup", "auto", "install"], check=True)
    configure_service_recovery()
    subprocess.run([sys.executable, str(service_script), "start"], check=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--parent-ip", default=None)
    parser.add_argument("--uninstall-token", required=True)
    parser.add_argument("--pythonw", default="pythonw.exe")
    args = parser.parse_args()
    copy_agent_files()
    write_secret()
    write_uninstall_hash(args.uninstall_token)
    apply_acls()
    configure_firewall(args.parent_ip)
    register_helper_run_key(args.pythonw)
    install_service()
    print("Kid PC Monitor service installed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
