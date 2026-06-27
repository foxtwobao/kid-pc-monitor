import builtins

import pytest

from scripts import install_service


def test_main_stops_existing_runtime_before_copying_files(monkeypatch):
    calls = []
    monkeypatch.setattr(install_service, "ensure_pywin32_available", lambda: calls.append("pywin32"))
    monkeypatch.setattr(install_service, "stop_existing_runtime", lambda: calls.append("stop"))
    monkeypatch.setattr(install_service, "copy_agent_files", lambda: calls.append("copy"))
    monkeypatch.setattr(install_service, "write_secret", lambda: calls.append("secret"))
    monkeypatch.setattr(install_service, "write_uninstall_hash", lambda _token: calls.append("hash"))
    monkeypatch.setattr(install_service, "apply_acls", lambda: calls.append("acl"))
    monkeypatch.setattr(install_service, "configure_firewall", lambda _ip: calls.append("firewall"))
    monkeypatch.setattr(install_service, "register_helper_run_key", lambda _pythonw: calls.append("helper"))
    monkeypatch.setattr(install_service, "install_service", lambda: calls.append("install"))
    monkeypatch.setattr(install_service.sys, "argv", ["install_service.py", "--uninstall-token", "token"])

    assert install_service.main() == 0
    assert calls[:3] == ["pywin32", "stop", "copy"]


def test_copy_agent_files_includes_uninstaller(tmp_path, monkeypatch):
    monkeypatch.setattr(install_service, "PROGRAM_DIR", tmp_path / "Program")
    monkeypatch.setattr(install_service, "DATA_DIR", tmp_path / "Data")

    install_service.copy_agent_files()

    assert (tmp_path / "Program" / "src" / "windows_service.py").exists()
    assert (tmp_path / "Program" / "scripts" / "uninstall_service.py").exists()
    assert (tmp_path / "Program" / "requirements.txt").exists()


def test_main_checks_pywin32_before_install(monkeypatch):
    calls = []
    monkeypatch.setattr(install_service, "ensure_pywin32_available", lambda: calls.append("pywin32"))
    monkeypatch.setattr(install_service, "stop_existing_runtime", lambda: calls.append("stop"))
    monkeypatch.setattr(install_service, "copy_agent_files", lambda: calls.append("copy"))
    monkeypatch.setattr(install_service, "write_secret", lambda: calls.append("secret"))
    monkeypatch.setattr(install_service, "write_uninstall_hash", lambda _token: calls.append("hash"))
    monkeypatch.setattr(install_service, "apply_acls", lambda: calls.append("acl"))
    monkeypatch.setattr(install_service, "configure_firewall", lambda _ip: calls.append("firewall"))
    monkeypatch.setattr(install_service, "register_helper_run_key", lambda _pythonw: calls.append("helper"))
    monkeypatch.setattr(install_service, "install_service", lambda: calls.append("install"))
    monkeypatch.setattr(install_service.sys, "argv", ["install_service.py", "--uninstall-token", "token"])

    assert install_service.main() == 0
    assert calls[0] == "pywin32"


def test_ensure_pywin32_available_explains_missing_dependency(monkeypatch):
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "win32serviceutil":
            raise ImportError("missing")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    with pytest.raises(SystemExit) as excinfo:
        install_service.ensure_pywin32_available()

    assert "pywin32 is required" in str(excinfo.value)


def test_stop_existing_runtime_tolerates_stop_command_failure_when_service_stops(monkeypatch):
    commands = []
    states = iter(["RUNNING", "STOPPED"])

    def fake_run(command, **kwargs):
        commands.append(command)
        if command[:2] == ["sc.exe", "query"]:
            state = next(states)
            return type("Result", (), {"returncode": 0, "stdout": f"STATE              : 4  {state}"})()
        return type("Result", (), {"returncode": 1, "stdout": ""})()

    monkeypatch.setattr(install_service.subprocess, "run", fake_run)
    monkeypatch.setattr(install_service.time, "sleep", lambda _seconds: None)

    install_service.stop_existing_runtime()

    assert ["sc.exe", "stop", install_service.SERVICE_NAME] in commands
    assert any(command[0] == "powershell.exe" for command in commands)


def test_install_service_installs_new_service_with_current_python(monkeypatch):
    calls = []
    monkeypatch.setattr(install_service, "PROGRAM_DIR", install_service.Path(r"C:\Program Files\KidPCMonitor"))
    monkeypatch.setattr(install_service, "service_exists", lambda: False)
    monkeypatch.setattr(install_service.subprocess, "run", lambda command, check: calls.append(command))
    monkeypatch.setattr(install_service, "configure_service_recovery", lambda: None)

    install_service.install_service()

    assert calls[0][0] == install_service.sys.executable
    assert calls[0][-3:] == ["--startup", "auto", "install"]
    assert calls[1][0] == install_service.sys.executable
    assert calls[1][-1] == "start"


def test_install_service_updates_existing_service(monkeypatch):
    calls = []
    monkeypatch.setattr(install_service, "PROGRAM_DIR", install_service.Path(r"C:\Program Files\KidPCMonitor"))
    monkeypatch.setattr(install_service, "service_exists", lambda: True)
    monkeypatch.setattr(install_service.subprocess, "run", lambda command, check: calls.append(command))
    monkeypatch.setattr(install_service, "configure_service_recovery", lambda: None)

    install_service.install_service()

    assert calls[0][-3:] == ["--startup", "auto", "update"]
    assert calls[1][-1] == "start"
