from scripts import install_service


def test_copy_agent_files_includes_uninstaller(tmp_path, monkeypatch):
    monkeypatch.setattr(install_service, "PROGRAM_DIR", tmp_path / "Program")
    monkeypatch.setattr(install_service, "DATA_DIR", tmp_path / "Data")

    install_service.copy_agent_files()

    assert (tmp_path / "Program" / "src" / "windows_service.py").exists()
    assert (tmp_path / "Program" / "scripts" / "uninstall_service.py").exists()
    assert (tmp_path / "Program" / "requirements.txt").exists()


def test_install_service_uses_current_python(monkeypatch):
    calls = []
    monkeypatch.setattr(install_service, "PROGRAM_DIR", install_service.Path(r"C:\Program Files\KidPCMonitor"))
    monkeypatch.setattr(install_service.subprocess, "run", lambda command, check: calls.append(command))
    monkeypatch.setattr(install_service, "configure_service_recovery", lambda: None)

    install_service.install_service()

    assert calls[0][0] == install_service.sys.executable
    assert calls[0][-3:] == ["--startup", "auto", "install"]
    assert calls[1][0] == install_service.sys.executable
    assert calls[1][-1] == "start"
