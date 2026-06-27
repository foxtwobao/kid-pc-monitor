from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
import time
from typing import Callable

from src.enforcement import evaluate_policy
from src.policy import Policy
from src.state_store import AgentState, StateStore


class KidServiceCore:
    def __init__(
        self,
        policy_path: str | Path,
        state_path: str | Path,
        username_provider: Callable[[], str],
        now_provider: Callable[[], datetime],
        helper_sender: Callable[[dict], None],
    ):
        self.policy_path = Path(policy_path)
        self.state_store = StateStore(state_path)
        self.username_provider = username_provider
        self.now_provider = now_provider
        self.helper_sender = helper_sender
        self.state = self.state_store.load()
        self.sent_warnings: set[int] = set()

    def load_policy(self) -> Policy | None:
        if not self.policy_path.exists():
            return None
        return Policy.from_dict(json.loads(self.policy_path.read_text(encoding="utf-8")))

    def save_policy(self, policy: Policy) -> None:
        policy.validate()
        self.policy_path.parent.mkdir(parents=True, exist_ok=True)
        self.policy_path.write_text(json.dumps(policy.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8")

    def tick(self) -> None:
        policy = self.load_policy()
        if policy is None:
            return
        username = self.username_provider()
        self.state = self.state.for_today()
        decision = evaluate_policy(policy, self.state, username, self.now_provider())
        if decision.should_lock:
            self.helper_sender({"type": "lock", "reason": decision.reason})
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
        self.state_store.save(self.state)

    def handle_status(self, _body: dict) -> dict:
        policy = self.load_policy()
        return {
            "policy_version": policy.policy_version if policy else 0,
            "state": self.state.to_dict(),
        }

    def handle_apply_policy(self, body: dict) -> dict:
        policy = Policy.from_dict(body["policy"])
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
        return {"accepted_policy_version": policy.policy_version}

    def handle_lock(self, body: dict) -> dict:
        reason = body.get("reason", "manual")
        self.helper_sender({"type": "lock", "reason": reason})
        return {"lock_requested": True, "reason": reason}

    def handlers(self) -> dict[str, Callable[[dict], dict]]:
        return {
            "status": self.handle_status,
            "apply_policy": self.handle_apply_policy,
            "lock": self.handle_lock,
        }

    def run_forever(self, interval_seconds: int = 1) -> None:
        while True:
            self.tick()
            time.sleep(interval_seconds)
