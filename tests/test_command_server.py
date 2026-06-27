import pytest

from src.agent_auth import NonceStore, sign_message
from src.command_server import CommandDispatcher


def test_dispatcher_accepts_authenticated_status_command():
    calls = []
    dispatcher = CommandDispatcher(
        secret=b"dev-secret",
        nonce_store=NonceStore(),
        handlers={"status": lambda body: calls.append(body) or {"ok": True}},
        now=lambda: 1000,
    )
    envelope = sign_message({"command": "status"}, b"dev-secret", now=1000, nonce="abc")

    response = dispatcher.dispatch(envelope)

    assert response == {"ok": True}
    assert calls == [{"command": "status"}]


def test_dispatcher_rejects_unknown_command():
    dispatcher = CommandDispatcher(
        secret=b"dev-secret",
        nonce_store=NonceStore(),
        handlers={},
        now=lambda: 1000,
    )
    envelope = sign_message({"command": "clear_all"}, b"dev-secret", now=1000, nonce="abc")

    with pytest.raises(ValueError, match="unknown command"):
        dispatcher.dispatch(envelope)


def test_dispatcher_rejects_unsigned_command():
    dispatcher = CommandDispatcher(
        secret=b"dev-secret",
        nonce_store=NonceStore(),
        handlers={"status": lambda body: {"ok": True}},
        now=lambda: 1000,
    )

    with pytest.raises(Exception):
        dispatcher.dispatch({"body": {"command": "status"}})
