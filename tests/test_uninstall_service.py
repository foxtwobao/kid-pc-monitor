import hashlib

from scripts import uninstall_service
from scripts.uninstall_service import token_matches


def test_uninstall_token_matches_hash_file(tmp_path):
    token_file = tmp_path / "uninstall.sha256"
    token_file.write_text(hashlib.sha256(b"remove-me").hexdigest(), encoding="utf-8")

    assert token_matches("remove-me", token_file=token_file) is True
    assert token_matches("wrong", token_file=token_file) is False


def test_uninstall_service_uses_current_python(monkeypatch, tmp_path):
    calls = []
    token_file = tmp_path / "uninstall.sha256"
    token_file.write_text(hashlib.sha256(b"remove-me").hexdigest(), encoding="utf-8")
    monkeypatch.setattr(uninstall_service, "TOKEN_HASH_FILE", token_file)
    monkeypatch.setattr(uninstall_service, "PROGRAM_DIR", tmp_path)
    monkeypatch.setattr(uninstall_service, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(uninstall_service.subprocess, "run", lambda command, check: calls.append(command))
    monkeypatch.setattr(uninstall_service.shutil, "rmtree", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(uninstall_service.argparse.ArgumentParser, "parse_args", lambda self: type("Args", (), {"token": "remove-me", "preserve_logs": True})())

    assert uninstall_service.main() == 0

    assert calls[0][0] == uninstall_service.sys.executable
    assert calls[1][0] == uninstall_service.sys.executable
