import ctypes
import getpass
import sys

from src import windows_sessions
from src.windows_sessions import (
    active_remote_session_ids,
    active_session_ids,
    current_interactive_username,
    disconnect_active_sessions,
    select_interactive_username,
)


def test_current_interactive_username_falls_back_off_windows_or_returns_active_windows_user():
    username = current_interactive_username()
    local_user = getpass.getuser()

    if sys.platform == "win32":
        assert username
        assert username.split("\\")[-1] == local_user
    else:
        assert username == local_user


def test_select_interactive_username_prefers_active_session_user():
    sessions = [
        {"session_id": 1, "state": 4},
        {"session_id": 2, "state": 0},
    ]

    assert select_interactive_username(sessions, lambda session_id: f"user-{session_id}") == "user-2"


def test_select_interactive_username_ignores_empty_active_sessions():
    sessions = [
        {"session_id": 1, "state": 0},
        {"session_id": 2, "state": 0},
    ]

    assert select_interactive_username(sessions, lambda session_id: "" if session_id == 1 else "kid") == "kid"


def test_active_remote_session_ids_selects_active_rdp_sessions_only():
    sessions = [
        {"session_id": 1, "state": 0, "station_name": "console"},
        {"session_id": 2, "state": 0, "station_name": "rdp-tcp#0"},
        {"session_id": 3, "state": 4, "station_name": "rdp-tcp#1"},
    ]

    assert active_remote_session_ids(sessions) == [2]


def test_active_session_ids_selects_console_and_rdp_sessions():
    sessions = [
        {"session_id": 1, "state": 0, "station_name": "console"},
        {"session_id": 2, "state": 0, "station_name": "rdp-tcp#0"},
        {"session_id": 3, "state": 4, "station_name": "rdp-tcp#1"},
    ]

    assert active_session_ids(sessions) == [1, 2]


def test_disconnect_active_sessions_disconnects_every_active_session(monkeypatch):
    disconnected = []

    class FakeWtsApi:
        def WTSDisconnectSession(self, _server, session_id, _wait):
            disconnected.append(session_id)

    monkeypatch.setattr(windows_sessions.sys, "platform", "win32")
    monkeypatch.setattr(windows_sessions, "enumerate_sessions", lambda: [
        {"session_id": 1, "state": 0, "station_name": "console"},
        {"session_id": 2, "state": 0, "station_name": "rdp-tcp#0"},
        {"session_id": 3, "state": 4, "station_name": "rdp-tcp#1"},
    ])
    monkeypatch.setattr(ctypes, "windll", type("Windll", (), {"wtsapi32": FakeWtsApi()})(), raising=False)

    disconnect_active_sessions()

    assert disconnected == [1, 2]
