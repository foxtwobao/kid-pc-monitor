from src.web_panel import (
    DEVICE_SECRETS,
    PENDING_COMMANDS,
    child_install_command,
    command_body_from_legacy,
    configured_device_secrets,
    current_user_from_status,
    discovered_pcs,
    ensure_paired_devices_visible,
    is_policy_command,
    load_pending_commands,
    panel_port,
    record_pending_command,
    save_pending_commands,
    save_device_secret,
    load_device_profiles,
    sync_pending_command,
    client_status_from_status,
    today_usage_from_status,
    time_remaining_from_status,
    app,
)


def test_time_remaining_from_status_uses_daily_limit_and_usage():
    status = {
        "policy": {"daily_limit_minutes": 60, "bedtime_windows": []},
        "state": {"usage_seconds_by_user": {"kid": 30 * 60}},
        "current_user": "kid",
    }

    assert time_remaining_from_status(status) == "30 minutes"


def test_time_remaining_from_status_handles_missing_limit():
    assert time_remaining_from_status({"policy": None, "state": {}}) == "No limits set"


def test_panel_port_defaults_and_reads_environment(monkeypatch):
    monkeypatch.delenv("KID_PC_PANEL_PORT", raising=False)
    assert panel_port() == 5000

    monkeypatch.setenv("KID_PC_PANEL_PORT", "5055")
    assert panel_port() == 5055


def test_child_install_command_uses_parent_url_and_pairing_token(monkeypatch):
    monkeypatch.setenv("KID_PC_PAIRING_TOKEN", "pair-me")

    command = child_install_command("http://192.168.10.38:5000")

    assert "powershell -NoProfile -ExecutionPolicy Bypass -Command" in command
    assert "Install-KidPCMonitorChild" in command
    assert "-ParentUrl 'http://192.168.10.38:5000'" in command
    assert "-PairingToken 'pair-me'" in command


def test_current_user_from_status_reads_signed_status_body():
    assert current_user_from_status({"current_user": "DESKTOP\\kid"}) == "DESKTOP\\kid"


def test_today_usage_from_status_matches_monitored_domain_user():
    status = {
        "policy": {"monitored_users": ["Phil"]},
        "state": {
            "usage_seconds_by_user": {
                "DESKTOP\\Phil": 65 * 60,
                "DESKTOP\\admin": 10 * 60,
            }
        },
    }

    assert today_usage_from_status(status) == "1h 5m"


def test_client_status_from_status_distinguishes_active_locked_and_offline():
    assert client_status_from_status(None) == "Offline"
    assert client_status_from_status({"current_user": "DESKTOP\\kid", "state": {}}) == "Active"
    assert client_status_from_status({"current_user": "", "state": {}}) == "Locked/Disconnected"
    assert client_status_from_status({"state": {"active_lock_reason": "manual"}}) == "Locked (manual)"


def test_policy_commands_are_pending_sync_candidates():
    assert is_policy_command(command_body_from_legacy("SET_LIMIT:30")) is True
    assert is_policy_command(command_body_from_legacy("CLEAR_ALL")) is True
    assert is_policy_command(command_body_from_legacy("LOCK")) is False


def test_record_pending_command_tracks_latest_policy_change():
    PENDING_COMMANDS.clear()
    body = command_body_from_legacy("SET_LIMIT:30")

    record_pending_command("192.168.10.251", body, "offline")

    assert PENDING_COMMANDS["192.168.10.251"]["body"] == body
    assert PENDING_COMMANDS["192.168.10.251"]["last_error"] == "offline"


def test_sync_pending_command_removes_entry_after_success():
    PENDING_COMMANDS.clear()
    body = command_body_from_legacy("SET_LIMIT:30")
    record_pending_command("192.168.10.251", body, "offline")
    calls = []

    synced = sync_pending_command(
        "192.168.10.251",
        sender=lambda ip, pending_body: calls.append((ip, pending_body)) or (True, "ok"),
    )

    assert synced is True
    assert calls == [("192.168.10.251", body)]
    assert "192.168.10.251" not in PENDING_COMMANDS


def test_pending_commands_persist_to_disk(tmp_path):
    PENDING_COMMANDS.clear()
    pending_file = tmp_path / "pending.json"
    body = command_body_from_legacy("SET_LIMIT:30")

    record_pending_command("192.168.10.251", body, "offline", pending_file=pending_file)
    PENDING_COMMANDS.clear()
    load_pending_commands(pending_file)

    assert PENDING_COMMANDS["192.168.10.251"]["body"] == body


def test_sync_pending_command_updates_disk_after_success(tmp_path):
    PENDING_COMMANDS.clear()
    pending_file = tmp_path / "pending.json"
    body = command_body_from_legacy("SET_LIMIT:30")
    record_pending_command("192.168.10.251", body, "offline", pending_file=pending_file)

    synced = sync_pending_command(
        "192.168.10.251",
        sender=lambda _ip, _body: (True, "ok"),
        pending_file=pending_file,
    )

    assert synced is True
    assert load_pending_commands(pending_file) == {}


def test_pair_endpoint_persists_child_secret(tmp_path, monkeypatch):
    secret_file = tmp_path / "device_secrets.json"
    profile_file = tmp_path / "device_profiles.json"
    monkeypatch.setenv("KID_PC_PAIRING_TOKEN", "pair-me")
    monkeypatch.setenv("KID_PC_DEVICE_SECRETS_FILE", str(secret_file))
    monkeypatch.setenv("KID_PC_DEVICE_PROFILES_FILE", str(profile_file))
    DEVICE_SECRETS.clear()

    response = app.test_client().post(
        "/api/pair",
        json={
            "token": "pair-me",
            "ip": "192.168.10.251",
            "hostname": "kid-laptop",
            "secret": "a" * 64,
            "monitored_users": ["kid"],
        },
    )

    assert response.status_code == 200
    assert response.get_json()["success"] is True
    assert configured_device_secrets()["192.168.10.251"] == "a" * 64
    assert '"192.168.10.251"' in secret_file.read_text(encoding="utf-8")
    profiles = load_device_profiles(profile_file)
    assert profiles["192.168.10.251"]["hostname"] == "kid-laptop"
    assert profiles["192.168.10.251"]["monitored_users"] == ["kid"]


def test_index_shows_paired_device_from_disk(tmp_path, monkeypatch):
    secret_file = tmp_path / "device_secrets.json"
    profile_file = tmp_path / "device_profiles.json"
    secret_file.write_text('{"192.168.10.251": "' + "a" * 64 + '"}', encoding="utf-8")
    profile_file.write_text(
        '{"192.168.10.251": {"hostname": "kid-laptop", "monitored_users": ["kid"]}}',
        encoding="utf-8",
    )
    monkeypatch.setenv("KID_PC_DEVICE_SECRETS_FILE", str(secret_file))
    monkeypatch.setenv("KID_PC_DEVICE_PROFILES_FILE", str(profile_file))
    monkeypatch.setattr("src.web_panel.query_status", lambda _ip: None)
    discovered_pcs.clear()

    response = app.test_client().get("/")

    assert response.status_code == 200
    assert b"kid-laptop" in response.data
    assert b"192.168.10.251" in response.data
    assert b"Monitored Users:" in response.data
    assert b"kid" in response.data


def test_control_page_shows_monitored_users(monkeypatch):
    discovered_pcs.clear()
    discovered_pcs["192.168.10.251"] = {
        "hostname": "kid-laptop",
        "locked": False,
        "monitored_users": ["Phil"],
    }
    monkeypatch.setattr(
        "src.web_panel.query_status",
        lambda _ip: {
            "policy": {"monitored_users": ["Phil"], "daily_limit_minutes": 120, "bedtime_windows": []},
            "state": {"usage_seconds_by_user": {"DESKTOP\\Phil": 30 * 60}},
            "current_user": "DESKTOP\\Phil",
        },
    )
    monkeypatch.setattr("src.web_panel.sync_pending_command", lambda _ip: False)

    response = app.test_client().get("/control/192.168.10.251")

    assert response.status_code == 200
    assert b"Monitored Users:" in response.data
    assert b"Phil" in response.data
    assert b"Client Status:" in response.data
    assert b"Active" in response.data
    assert b"Today Usage:" in response.data
    assert b"30m" in response.data


def test_ensure_paired_devices_visible_keeps_existing_runtime_status(tmp_path, monkeypatch):
    secret_file = tmp_path / "device_secrets.json"
    profile_file = tmp_path / "device_profiles.json"
    secret_file.write_text('{"192.168.10.251": "' + "a" * 64 + '"}', encoding="utf-8")
    profile_file.write_text(
        '{"192.168.10.251": {"hostname": "kid-laptop", "monitored_users": ["kid"]}}',
        encoding="utf-8",
    )
    monkeypatch.setenv("KID_PC_DEVICE_SECRETS_FILE", str(secret_file))
    monkeypatch.setenv("KID_PC_DEVICE_PROFILES_FILE", str(profile_file))
    discovered_pcs.clear()
    discovered_pcs["192.168.10.251"] = {"hostname": "old-name", "locked": True}

    ensure_paired_devices_visible()

    assert discovered_pcs["192.168.10.251"]["hostname"] == "old-name"
    assert discovered_pcs["192.168.10.251"]["locked"] is True
    assert discovered_pcs["192.168.10.251"]["monitored_users"] == ["kid"]


def test_pair_endpoint_rejects_wrong_token(tmp_path, monkeypatch):
    secret_file = tmp_path / "device_secrets.json"
    monkeypatch.setenv("KID_PC_PAIRING_TOKEN", "pair-me")
    monkeypatch.setenv("KID_PC_DEVICE_SECRETS_FILE", str(secret_file))
    DEVICE_SECRETS.clear()

    response = app.test_client().post(
        "/api/pair",
        json={"token": "wrong", "ip": "192.168.10.251", "secret": "b" * 64},
    )

    assert response.status_code == 403
    assert not secret_file.exists()


def test_web_panel_pages_render_from_bundled_templates():
    client = app.test_client()

    index_response = client.get("/", base_url="http://192.168.10.38:5000")
    control_response = client.get("/control/192.168.10.251")

    assert index_response.status_code == 200
    assert b"Install-KidPCMonitorChild" in index_response.data
    assert control_response.status_code == 200
    assert b"setTimeout(function() { location.reload(); }, 30000);" in control_response.data


def test_locked_control_page_shows_unlock_action(monkeypatch):
    discovered_pcs.clear()
    discovered_pcs["192.168.10.251"] = {"hostname": "kid-laptop", "locked": True}
    monkeypatch.setattr(
        "src.web_panel.query_status",
        lambda _ip: {
            "policy": {"monitored_users": ["kid"], "daily_limit_minutes": None, "bedtime_windows": []},
            "state": {"active_lock_reason": "manual", "usage_seconds_by_user": {}},
            "current_user": "",
        },
    )
    monkeypatch.setattr("src.web_panel.sync_pending_command", lambda _ip: False)

    response = app.test_client().get("/control/192.168.10.251")

    assert response.status_code == 200
    assert b"Unlock Computer" in response.data
    assert b"performAction('clear_all')" in response.data


def test_save_device_secret_rejects_non_hex_secret(tmp_path):
    try:
        save_device_secret("192.168.10.251", "not-hex", secrets_file=tmp_path / "secrets.json")
    except ValueError as exc:
        assert "64 hex" in str(exc)
    else:
        raise AssertionError("expected invalid secret to be rejected")
