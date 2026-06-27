from __future__ import annotations

import ctypes
from dataclasses import dataclass
import getpass
import sys
import threading
from ctypes import wintypes


WTS_CURRENT_SERVER_HANDLE = 0
WTS_USER_NAME = 5
WTS_DOMAIN_NAME = 7
WTS_ACTIVE = 0
WTS_CONSOLE_CONNECT = 1
WTS_CONSOLE_DISCONNECT = 2
WTS_REMOTE_CONNECT = 3
WTS_REMOTE_DISCONNECT = 4
WTS_SESSION_LOGON = 5
WTS_SESSION_LOGOFF = 6
WTS_SESSION_LOCK = 7
WTS_SESSION_UNLOCK = 8

CONNECT_EVENTS = {WTS_CONSOLE_CONNECT, WTS_REMOTE_CONNECT, WTS_SESSION_LOGON, WTS_SESSION_UNLOCK}
DISCONNECT_EVENTS = {WTS_CONSOLE_DISCONNECT, WTS_REMOTE_DISCONNECT, WTS_SESSION_LOGOFF, WTS_SESSION_LOCK}


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


@dataclass
class SessionActivity:
    session_id: int
    username: str = ""
    station_name: str = ""
    active: bool = False
    connected: bool = False
    locked: bool = False

    def is_countable(self) -> bool:
        return bool(self.username and self.active and self.connected and not self.locked)


class SessionActivityTracker:
    """Track countable Windows sessions from WTS session change events."""

    def __init__(self, session_enumerator=enumerate_sessions, username_query=_query_session_username):
        self.session_enumerator = session_enumerator
        self.username_query = username_query
        self._sessions: dict[int, SessionActivity] = {}
        self._lock = threading.RLock()

    def refresh(self) -> None:
        sessions = self.session_enumerator()
        seen_session_ids = set()
        with self._lock:
            for session in sessions:
                session_id = int(session["session_id"])
                seen_session_ids.add(session_id)
                active = session.get("state") == WTS_ACTIVE
                current = self._sessions.get(session_id, SessionActivity(session_id=session_id))
                username = self.username_query(session_id) if active else current.username
                self._sessions[session_id] = SessionActivity(
                    session_id=session_id,
                    username=username,
                    station_name=str(session.get("station_name", "")),
                    active=active,
                    connected=active,
                    locked=current.locked,
                )
            for session_id in list(self._sessions):
                if session_id not in seen_session_ids:
                    self._sessions.pop(session_id, None)

    def handle_session_change(self, event_type: int, session_id: int) -> None:
        session_id = int(session_id)
        with self._lock:
            current = self._sessions.get(session_id, SessionActivity(session_id=session_id))
            if event_type == WTS_SESSION_LOGOFF:
                self._sessions.pop(session_id, None)
                return
            username = self.username_query(session_id) or current.username
            if event_type in CONNECT_EVENTS:
                current.active = True
                current.connected = True
                current.username = username
            if event_type in DISCONNECT_EVENTS:
                current.active = False
                current.connected = False
            if event_type == WTS_SESSION_LOCK:
                current.locked = True
            elif event_type in (WTS_SESSION_UNLOCK, WTS_SESSION_LOGON):
                current.locked = False
            self._sessions[session_id] = current

    def current_username(self) -> str:
        with self._lock:
            for session in self._sessions.values():
                if session.is_countable():
                    return session.username
        return ""


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
