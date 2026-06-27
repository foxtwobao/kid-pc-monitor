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
