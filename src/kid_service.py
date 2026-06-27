from __future__ import annotations

from datetime import datetime
import json
import os
from pathlib import Path
import time
from typing import Callable

from src.enforcement import evaluate_policy
from src.policy import BedtimeWindow, Policy
from src.state_store import AgentState, StateStore, atomic_write_json


class KidServiceCore:
    def __init__(
        self,
        policy_path: str | Path,
        state_path: str | Path,
        username_provider: Callable[[], str],
        now_provider: Callable[[], datetime],
        helper_sender: Callable[[dict], None],
        helper_clearer: Callable[[], None] | None = None,
        session_locker: Callable[[], None] | None = None,
        shutdown_sender: Callable[[int], None] | None = None,
        event_logger: Callable[[str, dict], None] | None = None,
    ):
        self.policy_path = Path(policy_path)
        self.state_store = StateStore(state_path)
        self.username_provider = username_provider
        self.now_provider = now_provider
        self.helper_sender = helper_sender
        self.helper_clearer = helper_clearer or (lambda: None)
        self.session_locker = session_locker or (lambda: None)
        self.shutdown_sender = shutdown_sender or self.default_shutdown_sender
        self.event_logger = event_logger or (lambda _event_type, _data: None)
        self.state = self.state_store.load()
        self.sent_warnings: set[int] = set()
        self.last_tick_at: datetime | None = None

    @staticmethod
    def default_shutdown_sender(seconds: int) -> None:
        os.system(f'shutdown /s /t {seconds} /c "Computer will shutdown in {seconds} seconds"')

    def load_policy(self) -> Policy | None:
        if not self.policy_path.exists():
            return None
        return Policy.from_dict(json.loads(self.policy_path.read_text(encoding="utf-8-sig")))

    def save_policy(self, policy: Policy) -> None:
        policy.validate()
        atomic_write_json(self.policy_path, policy.to_dict())

    def default_policy(self) -> Policy:
        return Policy(
            device_id="local-device",
            policy_version=0,
            daily_limit_minutes=None,
            bedtime_windows=[],
            monitored_users=[],
            exempt_users=[],
            warning_minutes=[15, 5, 1],
            temporary_extensions={},
            parent_panel_allowed_ips=[],
            updated_at=self.now_provider().isoformat(),
        )

    def next_policy(self, **changes) -> Policy:
        current = self.load_policy() or self.default_policy()
        data = current.to_dict()
        data.update(changes)
        data["policy_version"] = current.policy_version + 1
        data["updated_at"] = self.now_provider().isoformat()
        return Policy.from_dict(data)

    def tick(self) -> None:
        policy = self.load_policy()
        if policy is None:
            return
        username = self.username_provider()
        if not username:
            return
        now = self.now_provider()
        self.state = self.state.for_today()
        self.account_usage(username, now)
        decision = evaluate_policy(policy, self.state, username, now)
        if decision.should_lock:
            if self.state.active_lock_reason != decision.reason:
                self.request_lock(decision.reason or "unknown")
                self.event_logger("lock.requested", {"reason": decision.reason or "unknown"})
            self.state = AgentState(
                current_date=self.state.current_date,
                usage_seconds_by_user=self.state.usage_seconds_by_user,
                active_lock_reason=decision.reason,
                last_policy_version=policy.policy_version,
                unsent_event_cursor=self.state.unsent_event_cursor,
                helper_last_seen_at=self.state.helper_last_seen_at,
            )
        elif decision.warning_minutes is not None and decision.warning_minutes not in self.sent_warnings:
            self.sent_warnings.add(decision.warning_minutes)
            self.helper_sender({"type": "warning", "minutes": decision.warning_minutes})
        elif self.state.active_lock_reason is not None:
            self.helper_clearer()
            self.state = AgentState(
                current_date=self.state.current_date,
                usage_seconds_by_user=self.state.usage_seconds_by_user,
                active_lock_reason=None,
                last_policy_version=policy.policy_version,
                unsent_event_cursor=self.state.unsent_event_cursor,
                helper_last_seen_at=self.state.helper_last_seen_at,
            )
        self.state_store.save(self.state)

    def account_usage(self, username: str, now: datetime) -> None:
        if self.last_tick_at is None:
            self.last_tick_at = now
            return
        elapsed_seconds = int((now - self.last_tick_at).total_seconds())
        self.last_tick_at = now
        if elapsed_seconds <= 0:
            return
        usage = dict(self.state.usage_seconds_by_user)
        usage[username] = usage.get(username, 0) + elapsed_seconds
        self.state = AgentState(
            current_date=self.state.current_date,
            usage_seconds_by_user=usage,
            active_lock_reason=self.state.active_lock_reason,
            last_policy_version=self.state.last_policy_version,
            unsent_event_cursor=self.state.unsent_event_cursor,
            helper_last_seen_at=self.state.helper_last_seen_at,
        )

    def request_lock(self, reason: str) -> None:
        self.helper_sender({"type": "lock", "reason": reason})
        try:
            self.session_locker()
        except Exception as exc:
            self.event_logger("lock.session_locker_failed", {"error": str(exc)})

    def handle_status(self, _body: dict) -> dict:
        policy = self.load_policy()
        return {
            "policy_version": policy.policy_version if policy else 0,
            "policy": policy.to_dict() if policy else None,
            "state": self.state.to_dict(),
            "current_user": self.username_provider(),
        }

    def handle_apply_policy(self, body: dict) -> dict:
        policy = Policy.from_dict(body["policy"])
        return self.accept_policy(policy)

    def accept_policy(self, policy: Policy) -> dict:
        self.save_policy(policy)
        self.state = AgentState(
            current_date=self.state.current_date,
            usage_seconds_by_user=self.state.usage_seconds_by_user,
            active_lock_reason=self.state.active_lock_reason,
            last_policy_version=policy.policy_version,
            unsent_event_cursor=self.state.unsent_event_cursor,
            helper_last_seen_at=self.state.helper_last_seen_at,
        )
        self.state_store.save(self.state)
        self.event_logger("policy.accepted", {"version": policy.policy_version})
        return {"accepted_policy_version": policy.policy_version}

    def handle_set_limit(self, body: dict) -> dict:
        policy = self.next_policy(daily_limit_minutes=int(body["minutes"]))
        self.sent_warnings.clear()
        response = self.accept_policy(policy)
        response["daily_limit_minutes"] = policy.daily_limit_minutes
        return response

    def handle_add_lock_time(self, body: dict) -> dict:
        lock_time = body["time"]
        current = self.load_policy() or self.default_policy()
        windows = current.bedtime_windows + [BedtimeWindow(start=lock_time, end="23:59")]
        policy = self.next_policy(bedtime_windows=[window.to_dict() for window in windows])
        response = self.accept_policy(policy)
        response["lock_times"] = [window.start for window in policy.bedtime_windows]
        return response

    def handle_clear_usage_limit(self, _body: dict) -> dict:
        policy = self.next_policy(daily_limit_minutes=None)
        return self.accept_policy(policy)

    def handle_clear_lock_times(self, _body: dict) -> dict:
        policy = self.next_policy(bedtime_windows=[])
        return self.accept_policy(policy)

    def handle_clear_all(self, _body: dict) -> dict:
        policy = self.next_policy(daily_limit_minutes=None, bedtime_windows=[])
        return self.accept_policy(policy)

    def handle_lock(self, body: dict) -> dict:
        reason = body.get("reason", "manual")
        self.request_lock(reason)
        self.event_logger("lock.requested", {"reason": reason})
        return {"lock_requested": True, "reason": reason}

    def handle_message(self, body: dict) -> dict:
        text = str(body.get("message", ""))
        self.helper_sender({"type": "message", "text": text})
        self.event_logger("message.sent", {"length": len(text)})
        return {"message_sent": True}

    def handle_shutdown(self, body: dict) -> dict:
        seconds = int(body.get("seconds", 60))
        self.shutdown_sender(seconds)
        self.event_logger("shutdown.requested", {"seconds": seconds})
        return {"shutdown_requested": True, "seconds": seconds}

    def handlers(self) -> dict[str, Callable[[dict], dict]]:
        return {
            "status": self.handle_status,
            "apply_policy": self.handle_apply_policy,
            "set_limit": self.handle_set_limit,
            "add_lock_time": self.handle_add_lock_time,
            "clear_usage_limit": self.handle_clear_usage_limit,
            "clear_lock_times": self.handle_clear_lock_times,
            "clear_all": self.handle_clear_all,
            "lock": self.handle_lock,
            "message": self.handle_message,
            "shutdown": self.handle_shutdown,
        }

    def run_forever(self, interval_seconds: int = 1) -> None:
        while True:
            self.tick()
            time.sleep(interval_seconds)
