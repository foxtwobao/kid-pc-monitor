from __future__ import annotations

import ctypes
import sys
import tkinter as tk
from tkinter import messagebox

from src.helper_ipc import decode_message


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


def main() -> int:
    for line in sys.stdin:
        handle_message(decode_message(line))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
