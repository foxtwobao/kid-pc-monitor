import pytest

from src.policy import BedtimeWindow, Policy, PolicyValidationError


def test_policy_accepts_valid_daily_limit_and_bedtime():
    policy = Policy(
        device_id="kid-pc-1",
        policy_version=3,
        daily_limit_minutes=90,
        bedtime_windows=[BedtimeWindow(start="21:00", end="07:00")],
        monitored_users=["kid"],
        exempt_users=[],
        warning_minutes=[15, 5, 1],
        temporary_extensions={},
        parent_panel_allowed_ips=["192.168.10.10"],
        updated_at="2026-06-27T13:00:00+08:00",
    )

    policy.validate()

    assert policy.to_dict()["policy_version"] == 3


def test_policy_rejects_overlap_between_monitored_and_exempt_users():
    policy = Policy(
        device_id="kid-pc-1",
        policy_version=1,
        daily_limit_minutes=60,
        bedtime_windows=[],
        monitored_users=["kid"],
        exempt_users=["kid"],
        warning_minutes=[15, 5, 1],
        temporary_extensions={},
        parent_panel_allowed_ips=[],
        updated_at="2026-06-27T13:00:00+08:00",
    )

    with pytest.raises(PolicyValidationError, match="same user"):
        policy.validate()


def test_policy_rejects_invalid_bedtime_clock_value():
    with pytest.raises(PolicyValidationError, match="HH:MM"):
        BedtimeWindow(start="25:00", end="07:00").validate()


def test_policy_round_trips_from_dict():
    data = {
        "device_id": "kid-pc-1",
        "policy_version": 4,
        "daily_limit_minutes": 45,
        "bedtime_windows": [{"start": "20:30", "end": "06:45"}],
        "monitored_users": ["kid"],
        "exempt_users": [],
        "warning_minutes": [10, 1],
        "temporary_extensions": {"2026-06-27": 15},
        "parent_panel_allowed_ips": ["192.168.10.10"],
        "updated_at": "2026-06-27T13:00:00+08:00",
    }

    policy = Policy.from_dict(data)

    assert policy.to_dict() == data
