from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time

from src.policy import Policy
from src.state_store import AgentState


@dataclass(frozen=True)
class EnforcementDecision:
    should_lock: bool
    reason: str | None
    warning_minutes: int | None


def _parse_clock(value: str) -> time:
    hour, minute = map(int, value.split(":"))
    return time(hour=hour, minute=minute)


def _inside_window(now_time: time, start: time, end: time) -> bool:
    if start <= end:
        return start <= now_time < end
    return now_time >= start or now_time < end


def _user_is_monitored(policy: Policy, username: str) -> bool:
    if policy.monitored_users:
        return username in policy.monitored_users
    if policy.exempt_users:
        return username not in policy.exempt_users
    return True


def evaluate_policy(
    policy: Policy,
    state: AgentState,
    username: str,
    now: datetime,
) -> EnforcementDecision:
    if not _user_is_monitored(policy, username):
        return EnforcementDecision(False, None, None)

    now_time = now.time().replace(tzinfo=None)
    for window in policy.bedtime_windows:
        if _inside_window(now_time, _parse_clock(window.start), _parse_clock(window.end)):
            return EnforcementDecision(True, "bedtime", None)

    if policy.daily_limit_minutes is not None:
        used_seconds = state.usage_seconds_by_user.get(username, 0)
        limit_seconds = policy.daily_limit_minutes * 60
        remaining_seconds = limit_seconds - used_seconds
        if remaining_seconds <= 0:
            return EnforcementDecision(True, "daily_limit", None)
        remaining_minutes = max(1, int(remaining_seconds / 60))
        matching_warnings = [
            warning for warning in sorted(policy.warning_minutes, reverse=True)
            if remaining_minutes <= warning
        ]
        if matching_warnings:
            return EnforcementDecision(False, None, min(matching_warnings))

    return EnforcementDecision(False, None, None)
