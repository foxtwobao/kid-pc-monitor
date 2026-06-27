import getpass

from src.windows_sessions import current_interactive_username


def test_current_interactive_username_falls_back_off_windows():
    assert current_interactive_username() == getpass.getuser()
