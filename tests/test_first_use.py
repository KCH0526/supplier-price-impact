"""PR #40: first-use helpers and operator documents (no new business features)."""

import importlib.util
import socket
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("check_env", ROOT / "tools" / "check_env.py")
check_env = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check_env)


def test_python_version_check():
    assert check_env.check_python((3, 11, 9))[0] is True
    ok, msg = check_env.check_python((3, 12, 1))
    assert ok is False and "3.11" in msg
    ok, msg = check_env.check_python((3, 10, 0))
    assert ok is False and "3.11" in msg


def test_installed_packages_match_the_lock():
    ok, msg = check_env.check_packages(ROOT / "requirements-lock.txt")
    assert ok is True, msg


def test_missing_or_wrong_package_is_reported(tmp_path):
    lock = tmp_path / "lock.txt"
    lock.write_text("pandas==0.0.1\nnot-a-real-package-xyz==1.0\n", encoding="utf-8")
    ok, msg = check_env.check_packages(lock)
    assert ok is False and "pandas" in msg and "not-a-real-package-xyz" in msg and "requirements-lock.txt" in msg


def test_port_in_use_is_reported():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        s.listen()
        port = s.getsockname()[1]
        ok, msg = check_env.check_port(port)
        assert ok is False and str(port) in msg
    assert check_env.check_port(port)[0] is True


@pytest.mark.parametrize("folder", ["報價 資料", "成本資料%2026", "報價#1"])
def test_data_folder_writable_with_chinese_spaces_and_symbols(tmp_path, folder):
    d = tmp_path / folder
    ok, msg = check_env.check_folder(d)
    assert ok is True, msg
    assert list(d.iterdir()) == [], "the check must leave no files behind"


def test_unwritable_data_folder_is_reported(tmp_path, monkeypatch):
    def denied(*a, **k):
        raise PermissionError("Permission denied")
    monkeypatch.setattr(check_env.tempfile, "NamedTemporaryFile", denied)
    ok, msg = check_env.check_folder(tmp_path)
    assert ok is False and "無法寫入" in msg


def test_network_share_is_refused():
    ok, msg = check_env.check_folder(Path("//server/share/報價"))
    assert ok is False and "網路" in msg


def test_main_runs_and_reports_in_chinese(tmp_path, capsys):
    code = check_env.main(["--data-dir", str(tmp_path / "資料"), "--port", "0"])
    out = capsys.readouterr().out
    assert "Python" in out and "套件" in out and "資料夾" in out
    assert code in (0, 1)


def test_start_scripts_use_the_project_venv_without_changing_system_policy():
    bat = (ROOT / "start_windows.bat").read_text(encoding="utf-8")
    sh = (ROOT / "start_macos.command").read_text(encoding="utf-8")
    for text in (bat, sh):
        assert "tools" in text and "check_env.py" in text and "streamlit run app.py" in text
        assert "requirements-lock.txt" in text
    assert r".venv\Scripts\python.exe" in bat and "Set-ExecutionPolicy" not in bat
    assert ".venv/bin/python" in sh
    assert "0.0.0.0" not in bat + sh


def test_local_deployment_no_longer_tells_users_to_change_execution_policy():
    text = (ROOT / "docs" / "LOCAL_DEPLOYMENT.md").read_text(encoding="utf-8")
    assert "Set-ExecutionPolicy" not in text
    for must in ("start_windows.bat", "start_macos.command", "check_env.py", "8502", "引號", "再次啟動"):
        assert must in text, must


def test_first_use_checklist_covers_everything():
    text = (ROOT / "docs" / "FIRST_USE_CHECKLIST.md").read_text(encoding="utf-8")
    for must in ("安裝成功", "系統正常啟動", "Excel 可以匯入", "61,597.00", "報告可下載", "備份", "還原",
                 "資料庫位置", "客戶草稿", "只有本機", "GitHub", "實體電腦", "流程 A", "流程 B", "流程 C",
                 "1,026.12", "33.33%", "25.00%"):
        assert must in text, must
    for forbidden in ("已有真實企業客戶", "已通過客戶驗收", "支援多使用者"):
        assert forbidden not in text


def test_start_script_for_this_os_explains_missing_install(tmp_path):
    """Runs the real launcher of the current OS in an empty folder (no .venv): it must explain
    what to install in readable Chinese and stop, without starting anything."""
    import shutil
    import subprocess

    if sys.platform == "win32":
        shutil.copy(ROOT / "start_windows.bat", tmp_path / "start_windows.bat")
        cmd = ["cmd", "/c", str(tmp_path / "start_windows.bat")]
    else:
        shutil.copy(ROOT / "start_macos.command", tmp_path / "start_macos.command")
        cmd = ["bash", str(tmp_path / "start_macos.command")]
    out = subprocess.run(cmd, cwd=tmp_path, stdin=subprocess.DEVNULL, capture_output=True, timeout=60)
    text = out.stdout.decode("utf-8", errors="strict")
    assert out.returncode == 1
    assert "尚未安裝" in text and "requirements-lock.txt" in text and "LOCAL_DEPLOYMENT.md" in text
    assert not any(p.name in (".venv", "cases.db") for p in tmp_path.iterdir())
