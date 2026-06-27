import hashlib

from scripts.uninstall_service import token_matches


def test_uninstall_token_matches_hash_file(tmp_path):
    token_file = tmp_path / "uninstall.sha256"
    token_file.write_text(hashlib.sha256(b"remove-me").hexdigest(), encoding="utf-8")

    assert token_matches("remove-me", token_file=token_file) is True
    assert token_matches("wrong", token_file=token_file) is False
