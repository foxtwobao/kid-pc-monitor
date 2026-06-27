import shutil
import subprocess
import sys


def copy_src_tree(tmp_path):
    target = tmp_path / "install-root" / "src"
    shutil.copytree("src", target)
    return target


def test_helper_script_runs_from_installed_src_tree(tmp_path):
    src_dir = copy_src_tree(tmp_path)

    result = subprocess.run(
        [sys.executable, str(src_dir / "helper.py"), "--help"],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0
    assert "--command-file" in result.stdout


def test_windows_service_script_reaches_pywin32_check_from_installed_src_tree(tmp_path):
    src_dir = copy_src_tree(tmp_path)

    result = subprocess.run(
        [sys.executable, str(src_dir / "windows_service.py")],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 1
    if sys.platform == "win32":
        assert "Usage:" in result.stdout
    else:
        assert "pywin32 is required" in result.stderr
