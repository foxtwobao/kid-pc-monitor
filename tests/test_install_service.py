from scripts import install_service


def test_install_service_uses_current_python(monkeypatch):
    calls = []
    monkeypatch.setattr(install_service, "PROGRAM_DIR", install_service.Path(r"C:\Program Files\KidPCMonitor"))
    monkeypatch.setattr(install_service.subprocess, "run", lambda command, check: calls.append(command))
    monkeypatch.setattr(install_service, "configure_service_recovery", lambda: None)

    install_service.install_service()

    assert calls[0][0] == install_service.sys.executable
    assert calls[1][0] == install_service.sys.executable
