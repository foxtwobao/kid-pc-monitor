import time

import pytest

from src.agent_auth import AuthError, NonceStore, sign_message, verify_message


def test_signed_message_verifies_with_shared_secret():
    secret = b"dev-secret"
    envelope = sign_message({"command": "status"}, secret, now=1000, nonce="abc")

    body = verify_message(envelope, secret, now=1001, nonce_store=NonceStore())

    assert body == {"command": "status"}


def test_rejects_replayed_nonce():
    secret = b"dev-secret"
    store = NonceStore()
    envelope = sign_message({"command": "status"}, secret, now=1000, nonce="abc")

    verify_message(envelope, secret, now=1001, nonce_store=store)

    with pytest.raises(AuthError, match="replay"):
        verify_message(envelope, secret, now=1001, nonce_store=store)


def test_rejects_stale_timestamp():
    secret = b"dev-secret"
    envelope = sign_message({"command": "status"}, secret, now=1000, nonce="abc")

    with pytest.raises(AuthError, match="stale"):
        verify_message(envelope, secret, now=2000, nonce_store=NonceStore(), max_skew_seconds=60)


def test_rejects_tampered_body():
    secret = b"dev-secret"
    envelope = sign_message({"command": "status"}, secret, now=int(time.time()), nonce="abc")
    envelope["body"]["command"] = "clear_all"

    with pytest.raises(AuthError, match="signature"):
        verify_message(envelope, secret, now=int(time.time()), nonce_store=NonceStore())


def test_web_panel_builds_signed_command():
    from src.web_panel import build_signed_command

    envelope = build_signed_command(
        {"command": "lock"},
        secret_hex="6465762d736563726574",
        now=1000,
        nonce="abc",
    )

    body = verify_message(envelope, b"dev-secret", now=1000, nonce_store=NonceStore())

    assert body == {"command": "lock"}
