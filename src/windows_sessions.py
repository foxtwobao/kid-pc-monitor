from __future__ import annotations

import ctypes
import getpass
import sys
from ctypes import wintypes


WTS_CURRENT_SERVER_HANDLE = 0
WTS_USER_NAME = 5
WTS_DOMAIN_NAME = 7
WTS_ACTIVE = 0


class WTS_SESSION_INFO(ctypes.Structure):
    _fields_ = [
        ("session_id", wintypes.DWORD),
        ("station_name", wintypes.LPWSTR),
        ("state", wintypes.DWORD),
    ]


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
    """Return the active interactive user when running as a Windows service."""
    if sys.platform != "win32":
        return getpass.getuser()

    username = select_interactive_username(enumerate_sessions(), _query_session_username)
    if username:
        return username

    session_id = ctypes.windll.kernel32.WTSGetActiveConsoleSessionId()
    return _query_session_username(session_id)


def _query_session_username(session_id: int) -> str:
    username = _query_session_string(session_id, WTS_USER_NAME)
    domain = _query_session_string(session_id, WTS_DOMAIN_NAME)
    if username and domain:
        return f"{domain}\\{username}"
    return username


def enumerate_sessions() -> list[dict]:
    sessions_ptr = ctypes.POINTER(WTS_SESSION_INFO)()
    count = wintypes.DWORD()
    ok = ctypes.windll.wtsapi32.WTSEnumerateSessionsW(
        WTS_CURRENT_SERVER_HANDLE,
        0,
        1,
        ctypes.byref(sessions_ptr),
        ctypes.byref(count),
    )
    if not ok:
        return []
    try:
        return [
            {
                "session_id": sessions_ptr[index].session_id,
                "state": sessions_ptr[index].state,
            }
            for index in range(count.value)
        ]
    finally:
        ctypes.windll.wtsapi32.WTSFreeMemory(sessions_ptr)


def select_interactive_username(sessions: list[dict], query_username) -> str:
    for session in sessions:
        if session["state"] == WTS_ACTIVE:
            username = query_username(session["session_id"])
            if username:
                return username
    return ""
