from __future__ import annotations

import ctypes
import argparse
from pathlib import Path
import sys
import time
import tkinter as tk
from tkinter import messagebox

from src.helper_ipc import decode_message, read_commands


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


def run_command_file(path: Path, poll_seconds: float = 1.0) -> int:
    offset = 0
    while True:
        if path.exists():
            with path.open("r", encoding="utf-8") as handle:
                handle.seek(offset)
                for line in handle:
                    line = line.strip()
                    if line:
                        handle_message(decode_message(line))
                offset = handle.tell()
        time.sleep(poll_seconds)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--command-file")
    args = parser.parse_args()
    if args.command_file:
        return run_command_file(Path(args.command_file))
    return run_stdin()


if __name__ == "__main__":
    raise SystemExit(main())
