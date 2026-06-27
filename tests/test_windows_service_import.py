def test_windows_service_imports_without_pywin32_on_linux():
    import src.windows_service as windows_service

    assert callable(windows_service.build_core)
