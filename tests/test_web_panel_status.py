from src.web_panel import current_user_from_status, time_remaining_from_status


def test_time_remaining_from_status_uses_daily_limit_and_usage():
    status = {
        "policy": {"daily_limit_minutes": 60, "bedtime_windows": []},
        "state": {"usage_seconds_by_user": {"kid": 30 * 60}},
        "current_user": "kid",
    }

    assert time_remaining_from_status(status) == "30 minutes"


def test_time_remaining_from_status_handles_missing_limit():
    assert time_remaining_from_status({"policy": None, "state": {}}) == "No limits set"


def test_current_user_from_status_reads_signed_status_body():
    assert current_user_from_status({"current_user": "DESKTOP\\kid"}) == "DESKTOP\\kid"
