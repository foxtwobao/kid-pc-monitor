from __future__ import annotations

import argparse
import ctypes
import getpass
import os
from pathlib import Path
import sys
import threading
import time
import tkinter as tk
from tkinter import messagebox

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.helper_ipc import decode_message, read_commands


tray_controller = None


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


def format_remaining_tooltip(minutes: int | None) -> str:
    if minutes is None:
        return "Kid PC Monitor - no daily limit"
    return f"Kid PC Monitor - {minutes} minute(s) remaining"


class TrayController:
    def __init__(self):
        self.icon = None
        self._lock = threading.Lock()

    def start(self) -> None:
        try:
            import pystray
            from PIL import Image, ImageDraw
        except ImportError:
            return

        image = Image.new("RGB", (64, 64), "#1f6feb")
        draw = ImageDraw.Draw(image)
        draw.ellipse((10, 10, 54, 54), fill="#ffffff")
        draw.rectangle((29, 16, 35, 48), fill="#1f6feb")
        draw.rectangle((18, 29, 46, 35), fill="#1f6feb")

        self.icon = pystray.Icon(
            "KidPCMonitor",
            image,
            format_remaining_tooltip(None),
            menu=pystray.Menu(pystray.MenuItem("Kid PC Monitor", lambda _icon, _item: None, enabled=False)),
        )
        self.icon.run_detached()

    def update_remaining(self, minutes: int | None) -> None:
        with self._lock:
            if self.icon is not None:
                self.icon.title = format_remaining_tooltip(minutes)

    def notify_warning(self, minutes: int) -> bool:
        with self._lock:
            if self.icon is None:
                return False
            self.icon.notify(
                f"Computer will lock in {minutes} minute(s).",
                "Kid PC Monitor",
            )
            return True


def create_tray_controller() -> TrayController:
    tray = TrayController()
    tray.start()
    return tray


def lock_workstation() -> None:
    ctypes.windll.user32.LockWorkStation()


def show_warning(minutes: int) -> None:
    if tray_controller is not None and tray_controller.notify_warning(minutes):
        return
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


def update_remaining(minutes: int | None) -> None:
    if tray_controller is not None:
        tray_controller.update_remaining(minutes)


def handle_message(message: dict) -> None:
    if not message_targets_current_user(message):
        return
    if message["type"] == "lock":
        lock_workstation()
    elif message["type"] == "warning":
        show_warning(int(message["minutes"]))
    elif message["type"] == "remaining":
        raw_minutes = message.get("minutes")
        update_remaining(None if raw_minutes is None else int(raw_minutes))
    elif message["type"] == "message":
        show_message(str(message.get("text", "")))
    else:
        raise ValueError(f"unknown helper message: {message['type']}")


def run_stdin() -> int:
    for line in sys.stdin:
        handle_message(decode_message(line))
    return 0


def run_command_file(path: Path, poll_seconds: float = 1.0, offset_path: Path | None = None) -> int:
    global tray_controller
    tray_controller = create_tray_controller()
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
