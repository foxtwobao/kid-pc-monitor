from __future__ import annotations

import json
from typing import Any


def encode_message(message_type: str, **payload: Any) -> str:
    return json.dumps({"type": message_type, **payload}, sort_keys=True)


def decode_message(raw: str) -> dict[str, Any]:
    message = json.loads(raw)
    if "type" not in message:
        raise ValueError("IPC message missing type")
    return message
