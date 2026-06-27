from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
from typing import Callable


def append_event(path: str | Path, event_type: str, data: dict, now: Callable[[], str] | None = None) -> None:
    event_path = Path(path)
    event_path.parent.mkdir(parents=True, exist_ok=True)
    timestamp = now() if now else datetime.now().astimezone().isoformat()
    event = {"at": timestamp, "type": event_type, "data": data}
    with event_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, sort_keys=True) + "\n")


def read_events(path: str | Path) -> list[dict]:
    event_path = Path(path)
    if not event_path.exists():
        return []
    events = []
    with event_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return events
