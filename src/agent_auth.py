from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import hmac
import json
import time
import uuid
from typing import Any


class AuthError(ValueError):
    """Raised when a command envelope fails authentication."""


@dataclass
class NonceStore:
    seen: set[str] = field(default_factory=set)

    def accept(self, nonce: str) -> None:
        if nonce in self.seen:
            raise AuthError("replay detected")
        self.seen.add(nonce)


def _canonical_payload(body: dict[str, Any], timestamp: int, nonce: str) -> bytes:
    return json.dumps(
        {"body": body, "timestamp": timestamp, "nonce": nonce},
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _signature(body: dict[str, Any], secret: bytes, timestamp: int, nonce: str) -> str:
    return hmac.new(secret, _canonical_payload(body, timestamp, nonce), hashlib.sha256).hexdigest()


def sign_message(
    body: dict[str, Any],
    secret: bytes,
    now: int | None = None,
    nonce: str | None = None,
) -> dict[str, Any]:
    timestamp = int(now if now is not None else time.time())
    nonce_value = nonce or uuid.uuid4().hex
    return {
        "body": body,
        "timestamp": timestamp,
        "nonce": nonce_value,
        "signature": _signature(body, secret, timestamp, nonce_value),
    }


def verify_message(
    envelope: dict[str, Any],
    secret: bytes,
    now: int | None,
    nonce_store: NonceStore,
    max_skew_seconds: int = 300,
) -> dict[str, Any]:
    timestamp = int(envelope["timestamp"])
    current_time = int(now if now is not None else time.time())
    if abs(current_time - timestamp) > max_skew_seconds:
        raise AuthError("stale timestamp")
    body = envelope["body"]
    nonce = envelope["nonce"]
    expected = _signature(body, secret, timestamp, nonce)
    if not hmac.compare_digest(expected, envelope.get("signature", "")):
        raise AuthError("invalid signature")
    nonce_store.accept(nonce)
    return body
