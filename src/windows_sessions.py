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
                "station_name": sessions_ptr[index].station_name or "",
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


def active_remote_session_ids(sessions: list[dict]) -> list[int]:
    remote_session_ids = []
    for session in sessions:
        station_name = str(session.get("station_name", "")).lower()
        if session.get("state") == WTS_ACTIVE and station_name.startswith("rdp"):
            remote_session_ids.append(int(session["session_id"]))
    return remote_session_ids


def active_session_ids(sessions: list[dict]) -> list[int]:
    return [int(session["session_id"]) for session in sessions if session.get("state") == WTS_ACTIVE]


def _disconnect_session(session_id: int) -> None:
    ctypes.windll.wtsapi32.WTSDisconnectSession(
        WTS_CURRENT_SERVER_HANDLE,
        session_id,
        False,
    )


def disconnect_active_remote_sessions() -> None:
    if sys.platform != "win32":
        return
    for session_id in active_remote_session_ids(enumerate_sessions()):
        _disconnect_session(session_id)


def disconnect_active_sessions() -> None:
    if sys.platform != "win32":
        return
    for session_id in active_session_ids(enumerate_sessions()):
        _disconnect_session(session_id)
