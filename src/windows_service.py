from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.agent_auth import NonceStore
from src.command_server import CommandDispatcher, build_server
from src.event_log import append_event
from src.helper_ipc import append_command, clear_command_file
from src.kid_service import KidServiceCore
from src.windows_hardening import EVENT_LOG_PATH, HELPER_COMMAND_PATH, POLICY_PATH, SECRET_PATH, SERVICE_NAME, STATE_PATH
from src.windows_sessions import SessionActivityTracker, current_interactive_username, disconnect_active_sessions_for_users


def load_secret() -> bytes:
    return bytes.fromhex(Path(SECRET_PATH).read_text(encoding="utf-8").strip())


def build_core(session_tracker: SessionActivityTracker | None = None) -> KidServiceCore:
    username_provider = session_tracker.current_username if session_tracker is not None else current_interactive_username
    return KidServiceCore(
        policy_path=POLICY_PATH,
        state_path=STATE_PATH,
        username_provider=username_provider,
        now_provider=lambda: __import__("datetime").datetime.now().astimezone(),
        helper_sender=lambda message: append_command(HELPER_COMMAND_PATH, message),
        helper_clearer=lambda: clear_command_file(HELPER_COMMAND_PATH),
        session_locker=disconnect_active_sessions_for_users,
        event_logger=lambda event_type, data: append_event(EVENT_LOG_PATH, event_type, data),
    )


def should_continue(stop_event, interval_seconds: int = 1) -> bool:
    if stop_event is None:
        time.sleep(interval_seconds)
        return True
    return not stop_event.wait(interval_seconds)


def extract_session_change_session_id(data) -> int | None:
    if data is None:
        return None
    if isinstance(data, (tuple, list)):
        if not data:
            return None
        data = data[0]
    try:
        return int(data)
    except (TypeError, ValueError):
        return None


def run_agent(stop_event=None, session_tracker: SessionActivityTracker | None = None) -> None:
    session_tracker = session_tracker or SessionActivityTracker()
    session_tracker.refresh()
    core = build_core(session_tracker=session_tracker)
    dispatcher = CommandDispatcher(
        secret=load_secret(),
        nonce_store=NonceStore(),
        handlers=core.handlers(),
    )
    server = build_server("0.0.0.0", 9999, dispatcher)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        while should_continue(stop_event):
            session_tracker.refresh()
            core.tick()
    finally:
        server.shutdown()
        server.server_close()


try:
    import servicemanager
    import win32event
    import win32service
    import win32serviceutil
except ImportError:
    servicemanager = None
    win32event = None
    win32service = None
    win32serviceutil = None


if win32serviceutil is not None:

    class KidPCMonitorWindowsService(win32serviceutil.ServiceFramework):
        _svc_name_ = SERVICE_NAME
        _svc_display_name_ = "Kid PC Monitor Service"
        _svc_description_ = "Enforces local kid PC time limits and authenticated parent commands."

        def __init__(self, args):
            super().__init__(args)
            self.stop_event = win32event.CreateEvent(None, 0, 0, None)
            self._stop_requested = threading.Event()
            self.session_tracker = SessionActivityTracker()

        def GetAcceptedControls(self):
            accepted = super().GetAcceptedControls()
            return accepted | win32service.SERVICE_ACCEPT_SESSIONCHANGE

        def SvcStop(self):
            self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
            self._stop_requested.set()
            win32event.SetEvent(self.stop_event)

        def SvcOtherEx(self, control, event_type, data):
            if control != win32service.SERVICE_CONTROL_SESSIONCHANGE:
                return
            session_id = extract_session_change_session_id(data)
            if session_id is None:
                return
            self.session_tracker.handle_session_change(event_type, session_id)
            append_event(
                EVENT_LOG_PATH,
                "session.changed",
                {"event_type": int(event_type), "session_id": int(session_id)},
            )

        def SvcDoRun(self):
            servicemanager.LogInfoMsg("Kid PC Monitor Service starting")
            run_agent(self._stop_requested, self.session_tracker)
            servicemanager.LogInfoMsg("Kid PC Monitor Service stopped")


def main() -> int:
    if win32serviceutil is None:
        print("pywin32 is required to install or run KidPCMonitorService on Windows.", file=sys.stderr)
        return 1
    win32serviceutil.HandleCommandLine(KidPCMonitorWindowsService)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
