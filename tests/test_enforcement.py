from datetime import datetime, timezone

from src.enforcement import EnforcementDecision, evaluate_policy
from src.kid_service import KidServiceCore
from src.policy import BedtimeWindow, Policy
from src.state_store import AgentState


def make_policy(limit=60):
    return Policy(
        device_id="kid-pc-1",
        policy_version=1,
        daily_limit_minutes=limit,
        bedtime_windows=[BedtimeWindow(start="21:00", end="07:00")],
        monitored_users=["kid"],
        exempt_users=[],
        warning_minutes=[15, 5, 1],
        temporary_extensions={},
        parent_panel_allowed_ips=[],
        updated_at="2026-06-27T00:00:00+00:00",
    )


def make_state(seconds):
    return AgentState(
        current_date="2026-06-27",
        usage_seconds_by_user={"kid": seconds},
        active_lock_reason=None,
        last_policy_version=1,
        unsent_event_cursor=0,
        helper_last_seen_at=None,
    )


def test_locks_when_daily_limit_reached_offline():
    decision = evaluate_policy(
        policy=make_policy(limit=60),
        state=make_state(seconds=3600),
        username="kid",
        now=datetime(2026, 6, 27, 12, 0, tzinfo=timezone.utc),
    )

    assert decision == EnforcementDecision(should_lock=True, reason="daily_limit", warning_minutes=None)


def test_warns_when_limit_is_near():
    decision = evaluate_policy(
        policy=make_policy(limit=60),
        state=make_state(seconds=55 * 60),
        username="kid",
        now=datetime(2026, 6, 27, 12, 0, tzinfo=timezone.utc),
    )

    assert decision.should_lock is False
    assert decision.warning_minutes == 5


def test_locks_during_bedtime_window_that_crosses_midnight():
    decision = evaluate_policy(
        policy=make_policy(limit=999),
        state=make_state(seconds=0),
        username="kid",
        now=datetime(2026, 6, 27, 22, 0, tzinfo=timezone.utc),
    )

    assert decision.should_lock is True
    assert decision.reason == "bedtime"


def test_exempt_user_is_not_locked():
    policy = Policy(
        device_id="kid-pc-1",
        policy_version=1,
        daily_limit_minutes=1,
        bedtime_windows=[BedtimeWindow(start="21:00", end="07:00")],
        monitored_users=[],
        exempt_users=["parent"],
        warning_minutes=[15, 5, 1],
        temporary_extensions={},
        parent_panel_allowed_ips=[],
        updated_at="2026-06-27T00:00:00+00:00",
    )

    decision = evaluate_policy(
        policy=policy,
        state=make_state(seconds=9999),
        username="parent",
        now=datetime(2026, 6, 27, 22, 0, tzinfo=timezone.utc),
    )

    assert decision.should_lock is False
    assert decision.reason is None


def test_service_core_requests_lock_when_policy_says_lock(tmp_path):
    sent_messages = []
    policy_path = tmp_path / "policy.json"
    state_path = tmp_path / "state.json"
    policy = make_policy(limit=1)
    policy_path.write_text(__import__("json").dumps(policy.to_dict()), encoding="utf-8")

    core = KidServiceCore(
        policy_path=policy_path,
        state_path=state_path,
        username_provider=lambda: "kid",
        now_provider=lambda: datetime(2026, 6, 27, 12, 0, tzinfo=timezone.utc),
        helper_sender=sent_messages.append,
    )
    core.state = make_state(seconds=60)

    core.tick()

    assert sent_messages[-1] == {"type": "lock", "reason": "daily_limit"}
