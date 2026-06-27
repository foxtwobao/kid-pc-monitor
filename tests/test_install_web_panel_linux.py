import os
import subprocess
import sys


def test_linux_web_panel_unit_runs_module_from_repo_root():
    env = {**os.environ, "PYTHON": sys.executable}

    result = subprocess.run(
        ["bash", "scripts/install_web_panel_linux.sh", "cat-unit"],
        check=True,
        capture_output=True,
        env=env,
        text=True,
    )

    assert "WorkingDirectory=" in result.stdout
    assert "WorkingDirectory=" + os.getcwd() in result.stdout
    assert f"ExecStart={sys.executable} -m src.web_panel" in result.stdout
