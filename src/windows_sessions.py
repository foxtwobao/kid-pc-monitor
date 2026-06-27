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


class WTS_PROCESS_INFO(ctypes.Structure):
    _fields_ = [
        ("session_id", wintypes.DWORD),
        ("process_id", wintypes.DWORD),
        ("process_name", wintypes.LPWSTR),
        ("user_sid", ctypes.c_void_p),
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

    username = select_interactive_username(enumerate_sessions(), _query_session_username, is_session_unlocked)
    if username:
        return username

    session_id = ctypes.windll.kernel32.WTSGetActiveConsoleSessionId()
    if not is_session_unlocked(session_id):
        return ""
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


def enumerate_processes() -> list[dict]:
    if sys.platform != "win32":
        return []
    processes_ptr = ctypes.POINTER(WTS_PROCESS_INFO)()
    count = wintypes.DWORD()
    ok = ctypes.windll.wtsapi32.WTSEnumerateProcessesW(
        WTS_CURRENT_SERVER_HANDLE,
        0,
        1,
        ctypes.byref(processes_ptr),
        ctypes.byref(count),
    )
    if not ok:
        return []
    try:
        return [
            {
                "session_id": processes_ptr[index].session_id,
                "process_id": processes_ptr[index].process_id,
                "process_name": processes_ptr[index].process_name or "",
            }
            for index in range(count.value)
        ]
    finally:
        ctypes.windll.wtsapi32.WTSFreeMemory(processes_ptr)


def session_has_process(session_id: int, process_name: str, process_enumerator=enumerate_processes) -> bool:
    expected = process_name.lower()
    return any(
        int(process.get("session_id", -1)) == int(session_id)
        and str(process.get("process_name", "")).lower() == expected
        for process in process_enumerator()
    )


def is_session_unlocked(session_id: int) -> bool:
    if sys.platform != "win32":
        return True
    return not session_has_process(session_id, "LogonUI.exe")


def select_interactive_username(sessions: list[dict], query_username, query_unlocked=lambda _session_id: True) -> str:
    for session in sessions:
        if session["state"] == WTS_ACTIVE:
            if not query_unlocked(session["session_id"]):
                continue
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


def _username_variants(username: str) -> set[str]:
    normalized = username.strip()
    variants = {normalized, normalized.lower()}
    if "\\" in normalized:
        short = normalized.rsplit("\\", 1)[1]
        variants.update({short, short.lower()})
    if "@" in normalized:
        short = normalized.split("@", 1)[0]
        variants.update({short, short.lower()})
    return variants


def _name_matches(configured: str, actual: str) -> bool:
    return bool(_username_variants(configured) & _username_variants(actual))


def active_session_ids_for_users(sessions: list[dict], usernames: list[str], query_username) -> list[int]:
    session_ids = []
    for session in sessions:
        if session.get("state") != WTS_ACTIVE:
            continue
        session_username = query_username(int(session["session_id"]))
        if session_username and any(_name_matches(username, session_username) for username in usernames):
            session_ids.append(int(session["session_id"]))
    return session_ids


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


def disconnect_active_sessions_for_users(usernames: list[str]) -> None:
    if sys.platform != "win32" or not usernames:
        return
    for session_id in active_session_ids_for_users(enumerate_sessions(), usernames, _query_session_username):
        _disconnect_session(session_id)
