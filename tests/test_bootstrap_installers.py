from pathlib import Path


def test_parent_bootstrap_prints_child_one_liner():
    script = Path("scripts/install_parent.sh").read_text(encoding="utf-8")

    assert "raw.githubusercontent.com/foxtwobao/kid-pc-monitor" in script
    assert "Install-KidPCMonitorChild" in script
    assert "PAIRING_TOKEN" in script
    assert "-m src.web_panel" in script
    assert 'export KID_PC_PANEL_PORT="$PANEL_PORT"' in script
    assert "stop_existing_parent_panel" in script
    assert "lsof -tiTCP" in script
    assert "Stopping existing Kid PC Monitor parent panel" in script
    assert "Port ${PANEL_PORT} is already in use" in script


def test_child_bootstrap_installs_service_and_pairs_with_parent():
    script = Path("scripts/install_child.ps1").read_text(encoding="utf-8")

    assert "function Install-KidPCMonitorChild" in script
    assert "function Get-KidPCMonitorChildUser" in script
    assert "[string]$ChildUser" in script
    assert "Get-KidPCMonitorSelectableUsers" in script
    assert "Read-Host" in script
    assert "Select the Windows user to monitor" in script
    assert "scripts\\install_service.py" in script
    assert "agent.secret" in script
    assert "policy.json" in script
    assert "monitored_users" in script
    assert "/api/pair" in script
    assert "Invoke-RestMethod" in script
