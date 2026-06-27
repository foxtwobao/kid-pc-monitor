from src.windows_hardening import (
    DATA_DIR,
    PROGRAM_DIR,
    SERVICE_NAME,
    acl_script,
    firewall_script,
    service_recovery_command,
)


def test_acl_script_limits_standard_users_to_read_execute():
    script = acl_script()

    assert str(PROGRAM_DIR) in script
    assert str(DATA_DIR) in script
    assert '"Users:(OI)(CI)RX"' in script
    assert '"Administrators:(OI)(CI)F"' in script
    assert '"SYSTEM:(OI)(CI)F"' in script


def test_firewall_script_can_scope_parent_ip():
    script = firewall_script("192.168.10.10")

    assert "Kid PC Monitor Agent" in script
    assert "-LocalPort 9999" in script
    assert '-RemoteAddress "192.168.10.10"' in script
    assert "-Profile Any" in script
    assert "-Enabled True" in script


def test_service_recovery_command_restarts_service():
    command = service_recovery_command()

    assert command[:3] == ["sc.exe", "failure", SERVICE_NAME]
    assert "restart/60000/restart/60000/restart/60000" in command
