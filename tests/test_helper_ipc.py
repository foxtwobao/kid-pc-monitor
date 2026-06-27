import pytest

from src import helper
from src.helper_ipc import append_command, clear_command_file, decode_message, encode_message, read_commands


def test_helper_ipc_round_trips_message():
    raw = encode_message("warning", minutes=5)

    assert decode_message(raw) == {"type": "warning", "minutes": 5}


def test_helper_ipc_rejects_missing_type():
    with pytest.raises(ValueError, match="missing type"):
        decode_message("{}")


def test_helper_ipc_appends_and_reads_command_file(tmp_path):
    command_file = tmp_path / "helper_commands.jsonl"

    append_command(command_file, {"type": "lock", "reason": "daily_limit"})
    append_command(command_file, {"type": "warning", "minutes": 1})

    assert list(read_commands(command_file)) == [
        {"type": "lock", "reason": "daily_limit"},
        {"type": "warning", "minutes": 1},
    ]


def test_helper_ipc_can_resume_from_previous_offset(tmp_path):
    command_file = tmp_path / "helper_commands.jsonl"
    append_command(command_file, {"type": "message", "text": "old"})
    offset = command_file.stat().st_size
    append_command(command_file, {"type": "message", "text": "new"})

    assert list(read_commands(command_file, start_offset=offset)) == [
        {"type": "message", "text": "new"}
    ]


def test_helper_ipc_can_clear_command_file(tmp_path):
    command_file = tmp_path / "helper_commands.jsonl"
    append_command(command_file, {"type": "lock", "reason": "daily_limit"})

    clear_command_file(command_file)

    assert command_file.read_text(encoding="utf-8") == ""


def test_helper_ignores_lock_for_other_target_user(monkeypatch):
    locked = []
    monkeypatch.setattr(helper.getpass, "getuser", lambda: "foxandcat")
    monkeypatch.setattr(helper, "lock_workstation", lambda: locked.append(True))

    helper.handle_message({"type": "lock", "reason": "manual", "users": ["test"]})

    assert locked == []


def test_helper_handles_lock_for_matching_target_user(monkeypatch):
    locked = []
    monkeypatch.setattr(helper.getpass, "getuser", lambda: "test")
    monkeypatch.setattr(helper, "lock_workstation", lambda: locked.append(True))

    helper.handle_message({"type": "lock", "reason": "manual", "users": ["DESKTOP\\test"]})

    assert locked == [True]


def test_helper_ignores_message_for_other_target_user(monkeypatch):
    shown = []
    monkeypatch.setattr(helper.getpass, "getuser", lambda: "foxandcat")
    monkeypatch.setattr(helper, "show_message", lambda text: shown.append(text))

    helper.handle_message({"type": "message", "text": "Dinner time", "users": ["test"]})

    assert shown == []


def test_helper_handles_message_for_matching_target_user(monkeypatch):
    shown = []
    monkeypatch.setattr(helper.getpass, "getuser", lambda: "test")
    monkeypatch.setattr(helper, "show_message", lambda text: shown.append(text))

    helper.handle_message({"type": "message", "text": "Dinner time", "users": ["DESKTOP\\test"]})

    assert shown == ["Dinner time"]
