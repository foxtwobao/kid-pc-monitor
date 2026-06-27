import getpass
import sys

from src.windows_sessions import current_interactive_username, select_interactive_username


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
