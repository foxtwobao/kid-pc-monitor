import ctypes
import getpass
import sys

from src import windows_sessions
from src.windows_sessions import (
    WTS_REMOTE_CONNECT,
    WTS_REMOTE_DISCONNECT,
    WTS_SESSION_LOCK,
    WTS_SESSION_LOGOFF,
    WTS_SESSION_UNLOCK,
    SessionActivityTracker,
    active_remote_session_ids,
    active_session_ids,
    active_session_ids_for_users,
    current_interactive_username,
    disconnect_active_sessions,
    disconnect_active_sessions_for_users,
    session_has_process,
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


def test_select_interactive_username_ignores_locked_active_sessions():
    sessions = [
        {"session_id": 1, "state": 0},
        {"session_id": 2, "state": 0},
    ]

    assert select_interactive_username(
        sessions,
        lambda session_id: f"user-{session_id}",
        lambda session_id: session_id == 2,
    ) == "user-2"


def test_session_has_process_matches_name_and_session():
    processes = [
        {"session_id": 1, "process_name": "LogonUI.exe"},
        {"session_id": 2, "process_name": "explorer.exe"},
    ]

    assert session_has_process(1, "LogonUI.exe", lambda: processes) is True
    assert session_has_process(2, "LogonUI.exe", lambda: processes) is False


def test_session_activity_tracker_stops_countable_user_while_locked():
    tracker = SessionActivityTracker(
        session_enumerator=lambda: [{"session_id": 3, "state": 0, "station_name": "console"}],
        username_query=lambda session_id: "DESKTOP\\Phil" if session_id == 3 else "",
    )

    tracker.refresh()
    assert tracker.current_username() == "DESKTOP\\Phil"

    tracker.handle_session_change(WTS_SESSION_LOCK, 3)
    assert tracker.current_username() == ""

    tracker.handle_session_change(WTS_SESSION_UNLOCK, 3)
    assert tracker.current_username() == "DESKTOP\\Phil"


def test_session_activity_tracker_stops_countable_user_while_disconnected():
    tracker = SessionActivityTracker(
        session_enumerator=lambda: [{"session_id": 7, "state": 0, "station_name": "rdp-tcp#1"}],
        username_query=lambda session_id: "DESKTOP\\Phil" if session_id == 7 else "",
    )

    tracker.refresh()
    tracker.handle_session_change(WTS_REMOTE_DISCONNECT, 7)
    assert tracker.current_username() == ""

    tracker.handle_session_change(WTS_REMOTE_CONNECT, 7)
    assert tracker.current_username() == "DESKTOP\\Phil"


def test_session_activity_tracker_removes_logged_off_session():
    tracker = SessionActivityTracker(
        session_enumerator=lambda: [{"session_id": 3, "state": 0, "station_name": "console"}],
        username_query=lambda session_id: "DESKTOP\\Phil" if session_id == 3 else "",
    )

    tracker.refresh()
    tracker.handle_session_change(WTS_SESSION_LOGOFF, 3)

    assert tracker.current_username() == ""


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


def test_active_session_ids_for_users_matches_domain_qualified_names():
    sessions = [
        {"session_id": 1, "state": 0, "station_name": "console"},
        {"session_id": 2, "state": 0, "station_name": "rdp-tcp#0"},
        {"session_id": 3, "state": 0, "station_name": "rdp-tcp#1"},
    ]

    assert active_session_ids_for_users(
        sessions,
        ["test"],
        lambda session_id: {
            1: "DESKTOP\\foxandcat",
            2: "DESKTOP\\test",
            3: "",
        }[session_id],
    ) == [2]


def test_disconnect_active_sessions_for_users_skips_admin_session(monkeypatch):
    disconnected = []

    class FakeWtsApi:
        def WTSDisconnectSession(self, _server, session_id, _wait):
            disconnected.append(session_id)

    monkeypatch.setattr(windows_sessions.sys, "platform", "win32")
    monkeypatch.setattr(windows_sessions, "enumerate_sessions", lambda: [
        {"session_id": 1, "state": 0, "station_name": "console"},
        {"session_id": 2, "state": 0, "station_name": "rdp-tcp#0"},
    ])
    monkeypatch.setattr(
        windows_sessions,
        "_query_session_username",
        lambda session_id: "DESKTOP\\foxandcat" if session_id == 1 else "DESKTOP\\test",
    )
    monkeypatch.setattr(ctypes, "windll", type("Windll", (), {"wtsapi32": FakeWtsApi()})(), raising=False)

    disconnect_active_sessions_for_users(["test"])

    assert disconnected == [2]
