from src.helper import load_offset, save_offset


def test_helper_offset_round_trips(tmp_path):
    path = tmp_path / "offset.txt"

    save_offset(path, 42)

    assert load_offset(path) == 42


def test_helper_offset_defaults_to_zero_when_missing(tmp_path):
    assert load_offset(tmp_path / "missing.txt") == 0
