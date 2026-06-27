from datetime import datetime, timezone

from src.enforcement import EnforcementDecision, evaluate_policy, remaining_daily_limit_minutes
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


def test_remaining_daily_limit_minutes_rounds_positive_time_up():
    assert remaining_daily_limit_minutes(
        policy=make_policy(limit=60),
        state=make_state(seconds=(59 * 60) + 1),
        username="kid",
    ) == 1


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


def test_monitored_user_matches_windows_domain_qualified_name():
    decision = evaluate_policy(
        policy=make_policy(limit=60),
        state=make_state(seconds=3600),
        username="DESKTOP\\kid",
        now=datetime(2026, 6, 27, 12, 0, tzinfo=timezone.utc),
    )

    assert decision.should_lock is True
    assert decision.reason == "daily_limit"


def test_service_core_requests_lock_when_policy_says_lock(tmp_path):
    sent_messages = []
    locked_sessions = []
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
        session_locker=lambda users: locked_sessions.append(users),
    )
    core.state = make_state(seconds=60)

    core.tick()

    assert sent_messages[-1] == {"type": "lock", "reason": "daily_limit", "users": ["kid"]}
    assert locked_sessions == [["kid"]]


def test_service_core_can_apply_limit_command_without_network_dependency(tmp_path):
    sent_messages = []
    events = []
    policy_path = tmp_path / "policy.json"
    state_path = tmp_path / "state.json"
    core = KidServiceCore(
        policy_path=policy_path,
        state_path=state_path,
        username_provider=lambda: "kid",
        now_provider=lambda: datetime(2026, 6, 27, 12, 0, tzinfo=timezone.utc),
        helper_sender=sent_messages.append,
        event_logger=lambda event_type, data: events.append((event_type, data)),
    )

    response = core.handle_set_limit({"minutes": 30})

    assert response == {"accepted_policy_version": 1, "daily_limit_minutes": 30}
    assert core.load_policy().daily_limit_minutes == 30
    assert events == [("policy.accepted", {"version": 1})]


def test_service_core_loads_utf8_bom_policy_file(tmp_path):
    policy_path = tmp_path / "policy.json"
    policy_path.write_text(
        __import__("json").dumps(make_policy(limit=45).to_dict()),
        encoding="utf-8-sig",
    )
    core = KidServiceCore(
        policy_path=policy_path,
        state_path=tmp_path / "state.json",
        username_provider=lambda: "kid",
        now_provider=lambda: datetime(2026, 6, 27, 12, 0, tzinfo=timezone.utc),
        helper_sender=lambda message: None,
    )

    assert core.load_policy().daily_limit_minutes == 45


def test_service_core_logs_apply_policy_command(tmp_path):
    events = []
    policy = make_policy(limit=20)
    core = KidServiceCore(
        policy_path=tmp_path / "policy.json",
        state_path=tmp_path / "state.json",
        username_provider=lambda: "kid",
        now_provider=lambda: datetime(2026, 6, 27, 12, 0, tzinfo=timezone.utc),
        helper_sender=lambda message: None,
        event_logger=lambda event_type, data: events.append((event_type, data)),
    )

    response = core.handle_apply_policy({"policy": policy.to_dict()})

    assert response == {"accepted_policy_version": 1}
    assert events == [("policy.accepted", {"version": 1})]


def test_service_core_can_send_parent_message_to_helper(tmp_path):
    sent_messages = []
    events = []
    core = KidServiceCore(
        policy_path=tmp_path / "policy.json",
        state_path=tmp_path / "state.json",
        username_provider=lambda: "kid",
        now_provider=lambda: datetime(2026, 6, 27, 12, 0, tzinfo=timezone.utc),
        helper_sender=sent_messages.append,
        event_logger=lambda event_type, data: events.append((event_type, data)),
    )

    response = core.handle_message({"message": "Dinner time"})

    assert response == {"message_sent": True}
    assert sent_messages == [{"type": "message", "text": "Dinner time", "users": ["kid"]}]
    assert events == [("message.sent", {"length": 11})]


def test_service_core_parent_message_targets_monitored_user_not_admin(tmp_path):
    sent_messages = []
    policy_path = tmp_path / "policy.json"
    policy_path.write_text(__import__("json").dumps(make_policy(limit=999).to_dict()), encoding="utf-8")
    core = KidServiceCore(
        policy_path=policy_path,
        state_path=tmp_path / "state.json",
        username_provider=lambda: "DESKTOP\\foxandcat",
        now_provider=lambda: datetime(2026, 6, 27, 12, 0, tzinfo=timezone.utc),
        helper_sender=sent_messages.append,
    )

    core.handle_message({"message": "Dinner time"})

    assert sent_messages == [{"type": "message", "text": "Dinner time", "users": ["kid"]}]


def test_service_core_manual_lock_disconnects_remote_sessions(tmp_path):
    sent_messages = []
    locked_sessions = []
    events = []
    core = KidServiceCore(
        policy_path=tmp_path / "policy.json",
        state_path=tmp_path / "state.json",
        username_provider=lambda: "kid",
        now_provider=lambda: datetime(2026, 6, 27, 12, 0, tzinfo=timezone.utc),
        helper_sender=sent_messages.append,
        session_locker=lambda users: locked_sessions.append(users),
        event_logger=lambda event_type, data: events.append((event_type, data)),
    )

    response = core.handle_lock({"reason": "manual"})

    assert response == {"lock_requested": True, "reason": "manual"}
    assert sent_messages == [{"type": "lock", "reason": "manual", "users": ["kid"]}]
    assert locked_sessions == [["kid"]]
    assert events == [("lock.requested", {"reason": "manual"})]


def test_service_core_manual_lock_targets_monitored_user_not_admin(tmp_path):
    sent_messages = []
    locked_sessions = []
    policy_path = tmp_path / "policy.json"
    policy_path.write_text(__import__("json").dumps(make_policy(limit=999).to_dict()), encoding="utf-8")
    core = KidServiceCore(
        policy_path=policy_path,
        state_path=tmp_path / "state.json",
        username_provider=lambda: "DESKTOP\\foxandcat",
        now_provider=lambda: datetime(2026, 6, 27, 12, 0, tzinfo=timezone.utc),
        helper_sender=sent_messages.append,
        session_locker=lambda users: locked_sessions.append(users),
    )

    core.handle_lock({"reason": "manual"})
    core.tick()

    assert sent_messages == [
        {"type": "lock", "reason": "manual", "users": ["kid"]},
        {"type": "lock", "reason": "manual", "users": ["kid"]},
    ]
    assert locked_sessions == [["kid"], ["kid"]]


def test_service_core_can_request_shutdown(tmp_path):
    shutdown_calls = []
    events = []
    core = KidServiceCore(
        policy_path=tmp_path / "policy.json",
        state_path=tmp_path / "state.json",
        username_provider=lambda: "kid",
        now_provider=lambda: datetime(2026, 6, 27, 12, 0, tzinfo=timezone.utc),
        helper_sender=lambda message: None,
        shutdown_sender=shutdown_calls.append,
        event_logger=lambda event_type, data: events.append((event_type, data)),
    )

    response = core.handle_shutdown({"seconds": 30})

    assert response == {"shutdown_requested": True, "seconds": 30}
    assert shutdown_calls == [30]
    assert events == [("shutdown.requested", {"seconds": 30})]


def test_service_core_status_reports_current_user(tmp_path):
    core = KidServiceCore(
        policy_path=tmp_path / "policy.json",
        state_path=tmp_path / "state.json",
        username_provider=lambda: "DESKTOP\\kid",
        now_provider=lambda: datetime(2026, 6, 27, 12, 0, tzinfo=timezone.utc),
        helper_sender=lambda message: None,
    )

    status = core.handle_status({})

    assert status["current_user"] == "DESKTOP\\kid"


def test_service_core_accounts_usage_between_ticks(tmp_path):
    sent_messages = []
    times = iter(
        [
            datetime(2026, 6, 27, 12, 0, 0, tzinfo=timezone.utc),
            datetime(2026, 6, 27, 12, 0, 10, tzinfo=timezone.utc),
        ]
    )
    policy_path = tmp_path / "policy.json"
    state_path = tmp_path / "state.json"
    policy_path.write_text(__import__("json").dumps(make_policy(limit=60).to_dict()), encoding="utf-8")
    core = KidServiceCore(
        policy_path=policy_path,
        state_path=state_path,
        username_provider=lambda: "kid",
        now_provider=lambda: next(times),
        helper_sender=sent_messages.append,
    )

    core.tick()
    core.tick()

    assert core.state.usage_seconds_by_user["kid"] == 10
    assert [message for message in sent_messages if message["type"] == "lock"] == []


def test_service_core_sends_remaining_update_when_minute_changes(tmp_path):
    sent_messages = []
    times = iter(
        [
            datetime(2026, 6, 27, 12, 0, 0, tzinfo=timezone.utc),
            datetime(2026, 6, 27, 12, 1, 0, tzinfo=timezone.utc),
            datetime(2026, 6, 27, 12, 1, 10, tzinfo=timezone.utc),
        ]
    )
    policy_path = tmp_path / "policy.json"
    state_path = tmp_path / "state.json"
    policy_path.write_text(__import__("json").dumps(make_policy(limit=60).to_dict()), encoding="utf-8")
    core = KidServiceCore(
        policy_path=policy_path,
        state_path=state_path,
        username_provider=lambda: "kid",
        now_provider=lambda: next(times),
        helper_sender=sent_messages.append,
    )

    core.tick()
    core.tick()
    core.tick()

    assert [message for message in sent_messages if message["type"] == "remaining"] == [
        {"type": "remaining", "minutes": 60, "users": ["kid"]},
        {"type": "remaining", "minutes": 59, "users": ["kid"]},
    ]


def test_service_core_clears_remaining_update_when_limit_is_removed(tmp_path):
    sent_messages = []
    times = iter(
        [
            datetime(2026, 6, 27, 12, 0, 0, tzinfo=timezone.utc),
            datetime(2026, 6, 27, 12, 0, 10, tzinfo=timezone.utc),
            datetime(2026, 6, 27, 12, 0, 20, tzinfo=timezone.utc),
        ]
    )
    policy_path = tmp_path / "policy.json"
    state_path = tmp_path / "state.json"
    policy_path.write_text(__import__("json").dumps(make_policy(limit=60).to_dict()), encoding="utf-8")
    core = KidServiceCore(
        policy_path=policy_path,
        state_path=state_path,
        username_provider=lambda: "kid",
        now_provider=lambda: next(times),
        helper_sender=sent_messages.append,
    )

    core.tick()
    core.handle_clear_usage_limit({})
    core.tick()

    assert [message for message in sent_messages if message["type"] == "remaining"] == [
        {"type": "remaining", "minutes": 60, "users": ["kid"]},
        {"type": "remaining", "minutes": None, "users": ["kid"]},
    ]


def test_service_core_sends_ten_minute_warning_once(tmp_path):
    sent_messages = []
    times = iter(
        [
            datetime(2026, 6, 27, 12, 0, 0, tzinfo=timezone.utc),
            datetime(2026, 6, 27, 12, 1, 0, tzinfo=timezone.utc),
            datetime(2026, 6, 27, 12, 1, 1, tzinfo=timezone.utc),
        ]
    )
    policy = make_policy(limit=11)
    policy = Policy.from_dict({**policy.to_dict(), "warning_minutes": [10]})
    policy_path = tmp_path / "policy.json"
    state_path = tmp_path / "state.json"
    policy_path.write_text(__import__("json").dumps(policy.to_dict()), encoding="utf-8")
    core = KidServiceCore(
        policy_path=policy_path,
        state_path=state_path,
        username_provider=lambda: "kid",
        now_provider=lambda: next(times),
        helper_sender=sent_messages.append,
    )

    core.tick()
    core.tick()
    core.tick()

    assert [message for message in sent_messages if message["type"] == "warning"] == [
        {"type": "warning", "minutes": 10, "users": ["kid"]}
    ]


def test_service_core_does_not_account_usage_without_interactive_user(tmp_path):
    times = iter(
        [
            datetime(2026, 6, 27, 12, 0, 0, tzinfo=timezone.utc),
            datetime(2026, 6, 27, 12, 0, 10, tzinfo=timezone.utc),
        ]
    )
    policy_path = tmp_path / "policy.json"
    state_path = tmp_path / "state.json"
    policy_path.write_text(__import__("json").dumps(make_policy(limit=1).to_dict()), encoding="utf-8")
    core = KidServiceCore(
        policy_path=policy_path,
        state_path=state_path,
        username_provider=lambda: "",
        now_provider=lambda: next(times),
        helper_sender=lambda message: None,
    )

    core.tick()
    core.tick()

    assert core.state.usage_seconds_by_user == {}
    assert core.state.active_lock_reason is None


def test_service_core_does_not_count_logged_out_gap_after_user_returns(tmp_path):
    current_time = {"value": datetime(2026, 6, 27, 12, 0, 0, tzinfo=timezone.utc)}
    current_user = {"value": "kid"}
    policy_path = tmp_path / "policy.json"
    state_path = tmp_path / "state.json"
    policy_path.write_text(__import__("json").dumps(make_policy(limit=60).to_dict()), encoding="utf-8")
    core = KidServiceCore(
        policy_path=policy_path,
        state_path=state_path,
        username_provider=lambda: current_user["value"],
        now_provider=lambda: current_time["value"],
        helper_sender=lambda message: None,
    )

    core.tick()
    current_user["value"] = ""
    current_time["value"] = datetime(2026, 6, 27, 12, 10, 0, tzinfo=timezone.utc)
    core.tick()
    current_user["value"] = "kid"
    current_time["value"] = datetime(2026, 6, 27, 12, 20, 0, tzinfo=timezone.utc)
    core.tick()
    current_time["value"] = datetime(2026, 6, 27, 12, 20, 30, tzinfo=timezone.utc)
    core.tick()

    assert core.state.usage_seconds_by_user["kid"] == 30


def test_service_core_locks_after_locally_accounted_usage_reaches_limit(tmp_path):
    sent_messages = []
    times = iter(
        [
            datetime(2026, 6, 27, 12, 0, 0, tzinfo=timezone.utc),
            datetime(2026, 6, 27, 12, 1, 0, tzinfo=timezone.utc),
        ]
    )
    policy_path = tmp_path / "policy.json"
    state_path = tmp_path / "state.json"
    policy_path.write_text(__import__("json").dumps(make_policy(limit=1).to_dict()), encoding="utf-8")
    core = KidServiceCore(
        policy_path=policy_path,
        state_path=state_path,
        username_provider=lambda: "kid",
        now_provider=lambda: next(times),
        helper_sender=sent_messages.append,
    )

    core.tick()
    core.tick()

    assert core.state.usage_seconds_by_user["kid"] == 60
    assert sent_messages[-1] == {"type": "lock", "reason": "daily_limit", "users": ["kid"]}


def test_service_core_sends_lock_once_while_limit_remains_active(tmp_path):
    sent_messages = []
    events = []
    times = iter(
        [
            datetime(2026, 6, 27, 12, 0, 0, tzinfo=timezone.utc),
            datetime(2026, 6, 27, 12, 1, 0, tzinfo=timezone.utc),
            datetime(2026, 6, 27, 12, 1, 1, tzinfo=timezone.utc),
        ]
    )
    policy_path = tmp_path / "policy.json"
    state_path = tmp_path / "state.json"
    policy_path.write_text(__import__("json").dumps(make_policy(limit=1).to_dict()), encoding="utf-8")
    core = KidServiceCore(
        policy_path=policy_path,
        state_path=state_path,
        username_provider=lambda: "kid",
        now_provider=lambda: next(times),
        helper_sender=sent_messages.append,
        event_logger=lambda event_type, data: events.append((event_type, data)),
    )

    core.tick()
    core.tick()
    core.tick()

    assert [message for message in sent_messages if message["type"] == "lock"] == [
        {"type": "lock", "reason": "daily_limit", "users": ["kid"]},
        {"type": "lock", "reason": "daily_limit", "users": ["kid"]},
    ]
    assert events == [("lock.requested", {"reason": "daily_limit"})]


def test_service_core_reasserts_manual_lock_until_cleared(tmp_path):
    sent_messages = []
    locked_sessions = []
    policy_path = tmp_path / "policy.json"
    state_path = tmp_path / "state.json"
    policy_path.write_text(__import__("json").dumps(make_policy(limit=999).to_dict()), encoding="utf-8")
    core = KidServiceCore(
        policy_path=policy_path,
        state_path=state_path,
        username_provider=lambda: "kid",
        now_provider=lambda: datetime(2026, 6, 27, 12, 0, tzinfo=timezone.utc),
        helper_sender=sent_messages.append,
        session_locker=lambda users: locked_sessions.append(users),
    )

    core.handle_lock({"reason": "manual"})
    core.tick()
    core.handle_clear_all({})

    assert [message for message in sent_messages if message["type"] == "lock"] == [
        {"type": "lock", "reason": "manual", "users": ["kid"]},
        {"type": "lock", "reason": "manual", "users": ["kid"]},
    ]
    assert locked_sessions == [["kid"], ["kid"]]
    assert core.state.active_lock_reason is None


def test_service_core_clears_stale_lock_reason_when_policy_no_longer_locks(tmp_path):
    sent_messages = []
    cleared = []
    policy_path = tmp_path / "policy.json"
    state_path = tmp_path / "state.json"
    policy_path.write_text(__import__("json").dumps(make_policy(limit=60).to_dict()), encoding="utf-8")
    core = KidServiceCore(
        policy_path=policy_path,
        state_path=state_path,
        username_provider=lambda: "kid",
        now_provider=lambda: datetime(2026, 6, 27, 12, 0, tzinfo=timezone.utc),
        helper_sender=sent_messages.append,
        helper_clearer=lambda: cleared.append(True),
    )
    core.state = make_state(seconds=10)
    core.state = type(core.state)(
        current_date=core.state.current_date,
        usage_seconds_by_user=core.state.usage_seconds_by_user,
        active_lock_reason="daily_limit",
        last_policy_version=core.state.last_policy_version,
        unsent_event_cursor=core.state.unsent_event_cursor,
        helper_last_seen_at=core.state.helper_last_seen_at,
    )

    core.handle_clear_usage_limit({})
    core.tick()

    assert core.state.active_lock_reason is None
    assert cleared == [True]
