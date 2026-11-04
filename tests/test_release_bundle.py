"""Local release bundle (tools/build_release.py): allow-list, integrity, reproducibility, usability."""

import hashlib
import importlib.util
import re
import subprocess
import sys
import tomllib
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("build_release", ROOT / "tools" / "build_release.py")
br = importlib.util.module_from_spec(spec)
spec.loader.exec_module(br)
VERSION = "9.9.9-test"
PREFIX = f"SupplierPriceImpact-{VERSION}/"


@pytest.fixture(scope="module")
def bundle(tmp_path_factory):
    out = tmp_path_factory.mktemp("dist")
    zip_path = br.build(VERSION, out)
    target = tmp_path_factory.mktemp("交付 測試") / "解壓 後"
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(target)
    return zip_path, target / PREFIX.rstrip("/")


def test_same_sources_give_a_byte_identical_zip(bundle, tmp_path):
    again = br.build(VERSION, tmp_path)
    assert hashlib.sha256(again.read_bytes()).digest() == hashlib.sha256(bundle[0].read_bytes()).digest()


def test_manifest_verifies_and_lists_every_file(bundle):
    assert br.verify(bundle[1]) == []


def test_contents_follow_the_allow_list(bundle):
    names = {n[len(PREFIX):] for n in zipfile.ZipFile(bundle[0]).namelist()}
    required = {"app.py", "core/case_store.py", "pages/4_案件工作台.py", ".streamlit/config.toml",
                "requirements-lock.txt", "requirements.txt", "start_windows.bat", "start_macos.command",
                "tools/check_env.py", "README.md", "docs/USER_GUIDE.md", "docs/FIRST_USE_CHECKLIST.md",
                "docs/LOCAL_DEPLOYMENT.md", "docs/images/02_summary.png", "samples/sample_bom.xlsx",
                "samples/rfq/rfq_sample.xlsx", "samples/historical/mapping_sales_dept.json", "MANIFEST.sha256"}
    assert required <= names
    for name in names:
        assert not re.search(r"(^|/)(\.git|\.venv|__pycache__|\.pytest_cache|tests|web|web_src)/", name), name
        assert not re.search(r"\.(db|sqlite3?|db-journal|pem|key|pfx|p12|pyc)$|\.env|secret|backup|before_restore",
                             name, re.I), name
    for internal in ("docs/WORK_LOG.md", "docs/REPOSITORY_INVENTORY.md", "docs/IMPLEMENTATION_SPEC.md",
                     "docs/GO_TO_MARKET.md", "docs/launch/README.md", "tools/build_release.py"):
        assert internal not in names


def test_forbidden_file_stops_the_build(tmp_path, monkeypatch):
    (tmp_path / "samples").mkdir()
    (tmp_path / "samples" / "cases.db").write_bytes(b"x")
    monkeypatch.setattr(br, "ALLOW", ["samples/*"])
    with pytest.raises(SystemExit, match="禁止打包"):
        br.selected_files(tmp_path)


def test_launchers_keep_their_line_endings_and_mode(bundle):
    zf = zipfile.ZipFile(bundle[0])
    bat = zf.read(PREFIX + "start_windows.bat")
    assert b"\r\n" in bat and b"\n" not in bat.replace(b"\r\n", b"")
    cmd = zf.getinfo(PREFIX + "start_macos.command")
    assert b"\r" not in zf.read(cmd) and (cmd.external_attr >> 16) & 0o777 == 0o755


def test_local_only_settings_are_shipped(bundle):
    cfg = tomllib.loads((bundle[1] / ".streamlit" / "config.toml").read_text(encoding="utf-8"))
    assert cfg["server"]["address"] == "127.0.0.1" and cfg["browser"]["gatherUsageStats"] is False
    assert '"127.0.0.1:8501:8501"' in (bundle[1] / "docker-compose.yml").read_text(encoding="utf-8")


def test_document_links_stay_inside_the_bundle(bundle):
    root = bundle[1]
    broken = []
    for md in root.rglob("*.md"):
        for target in re.findall(r"\]\(([^)\s]+)\)", md.read_text(encoding="utf-8")):
            if target.startswith(("http://", "https://", "mailto:", "#")):
                continue
            p = (md.parent / target.split("#")[0]).resolve()
            if not p.exists() or root.resolve() not in p.parents and p != root.resolve():
                broken.append(f"{md.relative_to(root)} -> {target}")
    assert broken == []
    assert br.INTERNAL_NOTE in (root / "docs" / "USER_GUIDE.md").read_text(encoding="utf-8")


def test_bundle_imports_reads_samples_and_runs_the_environment_check(bundle):
    root = bundle[1]
    code = ("import sys; sys.path.insert(0, '.');"
            "import core.case_store, core.rfq, core.calculator, core.report, core.customer_draft, core.quote_feedback;"
            "from core.reader import read_bom, read_price_increase;"
            "b = read_bom('samples/sample_bom.xlsx'); p = read_price_increase('samples/sample_price_increase.xlsx');"
            "r = core.rfq.read_rfq('samples/rfq/rfq_sample.xlsx');"
            "assert b.data is not None and p.data is not None and len(r.cases) == 4;"
            "print('bundle-ok', core.case_store.__file__)")
    import os
    utf8 = dict(os.environ, PYTHONIOENCODING="utf-8")  # Windows consoles default to cp1252
    out = subprocess.run([sys.executable, "-c", code], cwd=root, capture_output=True, text=True, encoding="utf-8",
                         env=utf8)
    assert out.returncode == 0, out.stderr
    # The modules must come from the extracted bundle, not from the source repository.
    loaded = Path(out.stdout.strip().split("bundle-ok ", 1)[1]).resolve()
    assert root.resolve() in loaded.parents
    env = subprocess.run([sys.executable, "tools/check_env.py", "--port", "0", "--data-dir", str(root / "報價 資料")],
                         cwd=root, capture_output=True, text=True, encoding="utf-8", env=utf8)
    assert "[OK] Python" in env.stdout and "[OK] 資料夾" in env.stdout
