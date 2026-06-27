import getpass
import sys

from src.windows_sessions import active_remote_session_ids, current_interactive_username, select_interactive_username


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
