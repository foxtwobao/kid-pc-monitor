from __future__ import annotations

import argparse
import ctypes
import getpass
import os
from pathlib import Path
import sys
import time
import tkinter as tk
from tkinter import messagebox

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.helper_ipc import decode_message, read_commands


def _username_variants(username: str) -> set[str]:
    normalized = username.strip()
    variants = {normalized, normalized.lower()}
    if "\\" in normalized:
        short = normalized.rsplit("\\", 1)[1]
        variants.update({short, short.lower()})
    if "@" in normalized:
        short = normalized.split("@", 1)[0]
        variants.update({short, short.lower()})
    return variants


def _name_matches(configured: str, actual: str) -> bool:
    return bool(_username_variants(configured) & _username_variants(actual))


def message_targets_current_user(message: dict) -> bool:
    users = message.get("users") or []
    if not users:
        return True
    current_user = getpass.getuser()
    return any(_name_matches(str(user), current_user) for user in users)


def default_offset_path() -> Path:
    base = os.environ.get("LOCALAPPDATA")
    if base:
        return Path(base) / "KidPCMonitor" / "helper.offset"
    return Path.home() / ".kid-pc-monitor-helper.offset"


def load_offset(path: Path) -> int:
    if not path.exists():
        return 0
    try:
        return int(path.read_text(encoding="utf-8").strip() or "0")
    except ValueError:
        return 0


def save_offset(path: Path, offset: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(offset), encoding="utf-8")


def lock_workstation() -> None:
    ctypes.windll.user32.LockWorkStation()


def show_warning(minutes: int) -> None:
    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    root.after(60000, root.destroy)
    messagebox.showwarning("Kid PC Monitor", f"Computer will lock in {minutes} minute(s).")
    root.destroy()


def show_message(text: str, title: str = "Kid PC Monitor") -> None:
    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    root.after(60000, root.destroy)
    messagebox.showwarning(title, text)
    root.destroy()


def handle_message(message: dict) -> None:
    if not message_targets_current_user(message):
        return
    if message["type"] == "lock":
        lock_workstation()
    elif message["type"] == "warning":
        show_warning(int(message["minutes"]))
    elif message["type"] == "message":
        show_message(str(message.get("text", "")))
    else:
        raise ValueError(f"unknown helper message: {message['type']}")


def run_stdin() -> int:
    for line in sys.stdin:
        handle_message(decode_message(line))
    return 0


def run_command_file(path: Path, poll_seconds: float = 1.0, offset_path: Path | None = None) -> int:
    offset_file = offset_path or default_offset_path()
    offset = load_offset(offset_file)
    while True:
        if path.exists():
            with path.open("r", encoding="utf-8") as handle:
                file_size = path.stat().st_size
                if offset > file_size:
                    offset = 0
                handle.seek(offset)
                for line in handle:
                    line = line.strip()
                    if line:
                        handle_message(decode_message(line))
                offset = handle.tell()
                save_offset(offset_file, offset)
        time.sleep(poll_seconds)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--command-file")
    parser.add_argument("--offset-file")
    args = parser.parse_args()
    if args.command_file:
        offset_path = Path(args.offset_file) if args.offset_file else None
        return run_command_file(Path(args.command_file), offset_path=offset_path)
    return run_stdin()


if __name__ == "__main__":
    raise SystemExit(main())
