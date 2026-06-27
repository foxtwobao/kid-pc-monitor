from src.web_panel import (
    PENDING_COMMANDS,
    command_body_from_legacy,
    current_user_from_status,
    is_policy_command,
    load_pending_commands,
    record_pending_command,
    save_pending_commands,
    sync_pending_command,
    time_remaining_from_status,
)


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


def test_policy_commands_are_pending_sync_candidates():
    assert is_policy_command(command_body_from_legacy("SET_LIMIT:30")) is True
    assert is_policy_command(command_body_from_legacy("CLEAR_ALL")) is True
    assert is_policy_command(command_body_from_legacy("LOCK")) is False


def test_record_pending_command_tracks_latest_policy_change():
    PENDING_COMMANDS.clear()
    body = command_body_from_legacy("SET_LIMIT:30")

    record_pending_command("192.168.10.251", body, "offline")

    assert PENDING_COMMANDS["192.168.10.251"]["body"] == body
    assert PENDING_COMMANDS["192.168.10.251"]["last_error"] == "offline"


def test_sync_pending_command_removes_entry_after_success():
    PENDING_COMMANDS.clear()
    body = command_body_from_legacy("SET_LIMIT:30")
    record_pending_command("192.168.10.251", body, "offline")
    calls = []

    synced = sync_pending_command(
        "192.168.10.251",
        sender=lambda ip, pending_body: calls.append((ip, pending_body)) or (True, "ok"),
    )

    assert synced is True
    assert calls == [("192.168.10.251", body)]
    assert "192.168.10.251" not in PENDING_COMMANDS


def test_pending_commands_persist_to_disk(tmp_path):
    PENDING_COMMANDS.clear()
    pending_file = tmp_path / "pending.json"
    body = command_body_from_legacy("SET_LIMIT:30")

    record_pending_command("192.168.10.251", body, "offline", pending_file=pending_file)
    PENDING_COMMANDS.clear()
    load_pending_commands(pending_file)

    assert PENDING_COMMANDS["192.168.10.251"]["body"] == body


def test_sync_pending_command_updates_disk_after_success(tmp_path):
    PENDING_COMMANDS.clear()
    pending_file = tmp_path / "pending.json"
    body = command_body_from_legacy("SET_LIMIT:30")
    record_pending_command("192.168.10.251", body, "offline", pending_file=pending_file)

    synced = sync_pending_command(
        "192.168.10.251",
        sender=lambda _ip, _body: (True, "ok"),
        pending_file=pending_file,
    )

    assert synced is True
    assert load_pending_commands(pending_file) == {}
