import pytest

from src.helper_ipc import append_command, decode_message, encode_message, read_commands


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
