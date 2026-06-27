import pytest

from src.helper_ipc import decode_message, encode_message


def test_helper_ipc_round_trips_message():
    raw = encode_message("warning", minutes=5)

    assert decode_message(raw) == {"type": "warning", "minutes": 5}


def test_helper_ipc_rejects_missing_type():
    with pytest.raises(ValueError, match="missing type"):
        decode_message("{}")
