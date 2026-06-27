from __future__ import annotations

import ctypes
import getpass
import os
import sys


WTS_CURRENT_SERVER_HANDLE = 0
WTS_USER_NAME = 5
WTS_DOMAIN_NAME = 7


def _query_session_string(session_id: int, info_class: int) -> str:
    buffer = ctypes.c_void_p()
    bytes_returned = ctypes.c_ulong()
    ok = ctypes.windll.wtsapi32.WTSQuerySessionInformationW(
        WTS_CURRENT_SERVER_HANDLE,
        session_id,
        info_class,
        ctypes.byref(buffer),
        ctypes.byref(bytes_returned),
    )
    if not ok:
        return ""
    try:
        return ctypes.wstring_at(buffer)
    finally:
        ctypes.windll.wtsapi32.WTSFreeMemory(buffer)


def current_interactive_username() -> str:
    """Return the active console user when running as a Windows service."""
    if sys.platform != "win32":
        return getpass.getuser()

    session_id = ctypes.windll.kernel32.WTSGetActiveConsoleSessionId()
    username = _query_session_string(session_id, WTS_USER_NAME)
    domain = _query_session_string(session_id, WTS_DOMAIN_NAME)
    if username and domain:
        return f"{domain}\\{username}"
    if username:
        return username
    return os.environ.get("USERNAME") or getpass.getuser()
