from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def encode_message(message_type: str, **payload: Any) -> str:
    return json.dumps({"type": message_type, **payload}, sort_keys=True)


def decode_message(raw: str) -> dict[str, Any]:
    message = json.loads(raw)
    if "type" not in message:
        raise ValueError("IPC message missing type")
    return message


def append_command(path: str | Path, message: dict[str, Any]) -> None:
    command_path = Path(path)
    command_path.parent.mkdir(parents=True, exist_ok=True)
    with command_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(message, sort_keys=True) + "\n")


def clear_command_file(path: str | Path) -> None:
    command_path = Path(path)
    command_path.parent.mkdir(parents=True, exist_ok=True)
    command_path.write_text("", encoding="utf-8")


def read_commands(path: str | Path, start_offset: int = 0):
    command_path = Path(path)
    if not command_path.exists():
        return
    with command_path.open("r", encoding="utf-8") as handle:
        handle.seek(start_offset)
        for line in handle:
            line = line.strip()
            if line:
                yield decode_message(line)
