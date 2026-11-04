"""PR #37: reproducible installation and local-only deployment settings."""

import importlib.metadata as md
import re
import sys
import tomllib
from pathlib import Path

from packaging.markers import Marker

ROOT = Path(__file__).resolve().parents[1]


def _pins(name):
    pins = {}
    for line in (ROOT / name).read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        spec, _, marker = line.partition(";")
        m = re.fullmatch(r"([A-Za-z0-9_.\-]+)==([A-Za-z0-9_.]+)", spec.strip())
        assert m, f"{name}: 必須用 == 固定版本：{line}"
        pins[re.sub(r"[-_.]+", "-", m.group(1)).lower()] = (m.group(2), marker.strip() or None)
    return pins


def test_direct_dependencies_are_pinned_and_match_the_lock():
    direct, lock = _pins("requirements.txt"), _pins("requirements-lock.txt")
    assert set(direct) == {"pandas", "openpyxl", "streamlit", "pytest"}
    for name, pin in direct.items():
        assert lock[name] == pin


def test_accepted_versions_are_not_upgraded():
    lock = _pins("requirements-lock.txt")
    accepted = {"pandas": "3.1.0", "openpyxl": "3.1.5", "streamlit": "1.66.1", "pytest": "9.2.0", "numpy": "2.4.6"}
    for name, version in accepted.items():
        assert lock[name][0] == version


def test_installed_environment_matches_the_lock():
    """CI installs requirements-lock.txt, so the tested environment is exactly the locked one."""
    for name, (version, marker) in _pins("requirements-lock.txt").items():
        if marker and not Marker(marker).evaluate():
            continue
        assert md.version(name) == version, f"{name} 安裝的是 {md.version(name)}，鎖定的是 {version}"


def test_python_311():
    assert sys.version_info[:2] == (3, 11)


def test_ci_and_docker_install_from_the_lock():
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "pip install -r requirements-lock.txt" in ci
    # Ubuntu "test" stays the required check; Windows and macOS run the same locked install.
    assert "\n  test:\n" in ci and "windows-latest" in ci and "macos-latest" in ci
    assert 'python-version: "3.11"' in ci and 'node-version: "22"' in ci
    assert "requirements.txt" not in ci.replace("requirements-lock.txt", "")
    docker = (ROOT / "Dockerfile").read_text()
    assert "requirements-lock.txt" in docker and "-r requirements-lock.txt" in docker
    assert "FROM python:3.11-slim" in docker and "USER appuser" in docker


def test_local_only_defaults():
    cfg = tomllib.loads((ROOT / ".streamlit" / "config.toml").read_text(encoding="utf-8"))
    assert cfg["server"]["address"] == "127.0.0.1"
    assert cfg["browser"]["gatherUsageStats"] is False
    compose = (ROOT / "docker-compose.yml").read_text()
    assert '"127.0.0.1:8501:8501"' in compose and '- "8501:8501"' not in compose


def test_case_data_is_never_committed():
    for ignore in (".gitignore", ".dockerignore"):
        lines = (ROOT / ignore).read_text(encoding="utf-8").splitlines()
        for pattern in ("*.db", "*.sqlite", "*.sqlite3", "*.db-journal", "case_backups/", "case_data/"):
            assert pattern in lines, (ignore, pattern)


def test_deployment_guide_covers_required_topics_honestly():
    text = (ROOT / "docs" / "LOCAL_DEPLOYMENT.md").read_text(encoding="utf-8")
    for topic in ("Windows 安裝", "macOS 安裝", "Docker 啟動", "本機資料庫位置", "磁碟權限與加密", "## 8. 備份",
                  "## 9. 還原", "更新程式前的備份流程", "資料庫無法開啟", "備份損毀", "儲存空間不足", "權限不足",
                  "安裝套件失敗", "系統版本不相容", "requirements-lock.txt", "127.0.0.1", "尚未在實機驗證",
                  "不支援多使用者", "沒有加密", "GitHub-hosted runner", "Docker Desktop"):
        assert topic in text, topic
    for forbidden in ("支援多使用者權限", "已通過真實 ERP", "已加密"):
        assert forbidden not in text
