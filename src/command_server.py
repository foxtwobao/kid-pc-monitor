from __future__ import annotations

import json
import socketserver
import time
from typing import Any, Callable

from src.agent_auth import NonceStore, verify_message


Handler = Callable[[dict[str, Any]], dict[str, Any]]


class CommandDispatcher:
    def __init__(
        self,
        secret: bytes,
        nonce_store: NonceStore,
        handlers: dict[str, Handler],
        now: Callable[[], int] | None = None,
    ):
        self.secret = secret
        self.nonce_store = nonce_store
        self.handlers = handlers
        self.now = now or (lambda: int(time.time()))

    def dispatch(self, envelope: dict[str, Any]) -> dict[str, Any]:
        body = verify_message(envelope, self.secret, self.now(), self.nonce_store)
        command = body.get("command")
        if command not in self.handlers:
            raise ValueError(f"unknown command: {command}")
        return self.handlers[command](body)


class JsonCommandHandler(socketserver.StreamRequestHandler):
    dispatcher: CommandDispatcher

    def handle(self) -> None:
        raw = self.rfile.readline(1024 * 1024)
        envelope = json.loads(raw.decode("utf-8"))
        try:
            response = {"success": True, "body": self.dispatcher.dispatch(envelope)}
        except Exception as exc:
            response = {"success": False, "error": str(exc)}
        self.wfile.write((json.dumps(response) + "\n").encode("utf-8"))


def build_server(host: str, port: int, dispatcher: CommandDispatcher) -> socketserver.ThreadingTCPServer:
    class BoundHandler(JsonCommandHandler):
        pass

    BoundHandler.dispatcher = dispatcher
    return socketserver.ThreadingTCPServer((host, port), BoundHandler)
