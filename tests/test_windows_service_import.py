def test_windows_service_imports_without_pywin32_on_linux():
    import src.windows_service as windows_service

    assert callable(windows_service.build_core)


def test_service_loop_continues_until_stop_event_is_set():
    import src.windows_service as windows_service

    class FakeEvent:
        def __init__(self, result):
            self.result = result

        def wait(self, _seconds):
            return self.result

    assert windows_service.should_continue(FakeEvent(False)) is True
    assert windows_service.should_continue(FakeEvent(True)) is False


def test_service_loop_sleeps_when_no_stop_event(monkeypatch):
    import src.windows_service as windows_service

    sleeps = []
    monkeypatch.setattr(windows_service.time, "sleep", sleeps.append)

    assert windows_service.should_continue(None, interval_seconds=2) is True
    assert sleeps == [2]


def test_build_core_uses_interactive_username_provider(monkeypatch, tmp_path):
    import src.windows_service as windows_service

    monkeypatch.setattr(windows_service, "POLICY_PATH", tmp_path / "policy.json")
    monkeypatch.setattr(windows_service, "STATE_PATH", tmp_path / "state.json")
    monkeypatch.setattr(windows_service, "HELPER_COMMAND_PATH", tmp_path / "helper_commands.jsonl")
    monkeypatch.setattr(windows_service, "current_interactive_username", lambda: "kid")

    core = windows_service.build_core()

    assert core.username_provider() == "kid"
