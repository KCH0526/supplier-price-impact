"""PR #39: SQLite paths with special characters, read-only checks, and full restore integrity.

Gaps not covered by PR #32-#38 tests. Synthetic data only.
"""

import sqlite3
import sys
from decimal import Decimal
from pathlib import Path, PurePosixPath, PureWindowsPath
from urllib.parse import unquote

import pytest

import core.case_store as cs
from core.case_store import CaseStore, StoreError, check_integrity
from core.quote_feedback import record_outcome
from core.rfq import read_rfq, save_rfq_cases, validate_transition

ROOT = Path(__file__).resolve().parents[1]
CASE = "C-001|RFQ-2612-001|v1"
D = Decimal
# Folder names users really create. In a SQLite URI '#' starts a fragment, '?' starts the
# query (so "?mode=ro" would be lost) and '%' starts an escape.
FOLDERS = ["報價#1", "what?", "成本資料%2026", "報價 資料 2026", "客戶報價資料", "50%20off"]
# Windows does not allow '?' in file or folder names (NTFS rule), so such folders cannot
# exist there; the Windows URI encoding of '?' is verified without the filesystem below.
if sys.platform == "win32":
    FOLDERS = [f for f in FOLDERS if "?" not in f]


def _files(root: Path) -> set:
    return {p.relative_to(root).as_posix() for p in root.rglob("*")}


def _populated(path: Path) -> CaseStore:
    """RFQ with 2 lines, 2 quote versions, status changes, a won outcome with actual cost."""
    store = CaseStore(path, enabled=True)
    store.initialize()
    assert save_rfq_cases(store, read_rfq(ROOT / "samples" / "rfq" / "rfq_sample.xlsx"), reason="合成 RFQ") == 4
    assert len(store.get_case(CASE)["lines"]) == 2
    for status in ("待人工覆核", "已產生報價草稿", "已報價"):
        store.update_case_status(CASE, status, reason=f"流程：{status}", validator=validate_transition)
    store.add_quote_version(CASE, "1", D("300"), D("100"), {"unit_cost": D("200")}, reason="首次報價")
    store.add_quote_version(CASE, "1", D("310"), D("100"), {"unit_cost": D("205.5")}, reason="客戶議價後")
    store.update_case_status(CASE, "成交", reason="客戶下單", validator=validate_transition)
    record_outcome(store, CASE, "1", 2, {"result": "成交", "won_quantity": D("100"), "actual_quantity": D("100"),
                                          "actual_total_cost": D("22500")}, reason="月結實際成本")
    return store


def _dump(path: Path) -> dict:
    """Every row of every table (plain connection, read only by use)."""
    con = sqlite3.connect(path)
    try:
        tables = [r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        return {t: con.execute(f"SELECT * FROM {t} ORDER BY rowid").fetchall() for t in tables}
    finally:
        con.close()


@pytest.mark.parametrize("folder", FOLDERS)
def test_integrity_check_reads_the_right_file_in_special_folders(tmp_path, folder):
    d = tmp_path / folder
    store = _populated(d / "cases.db")
    backup = store.backup(d / "backup.db")
    before = _files(tmp_path)
    info = check_integrity(backup)
    assert info == {"ok": True, "schema_version": 1, "message": "完整"}
    assert _files(tmp_path) == before, "a read-only check must not create any file"


@pytest.mark.parametrize("folder", FOLDERS)
def test_backup_and_restore_in_special_folders(tmp_path, folder):
    d = tmp_path / folder
    store = _populated(d / "cases.db")
    backup = store.backup(d / "backup.db")
    expected = _dump(backup)
    store.update_case_status(CASE, "待估價", reason="不會發生", validator=None)
    before = _files(tmp_path)
    previous = store.restore(backup, confirm=True)
    assert _dump(store.path) == expected
    assert _files(tmp_path) - before == {previous.relative_to(tmp_path).as_posix()}


@pytest.mark.parametrize("path", [PureWindowsPath(r"D:\報價資料\報價#1\成本資料%2026\a b?.db"),
                                  PurePosixPath("/Users/會計/報價#1/成本資料%2026/a b?.db")])
def test_uri_encoding_is_exact_on_windows_and_posix(path):
    """pathlib.as_uri percent-encodes every character SQLite would misread, on both path styles."""
    uri = path.as_uri()
    rest = uri[len("file://"):]
    assert "#" not in rest and "?" not in rest and " " not in rest
    assert "%23" in uri and "%3F" in uri and "%25" in uri and "%20" in uri
    assert unquote(rest).lstrip("/").replace("\\", "/").endswith("報價#1/成本資料%2026/a b?.db")


def test_missing_database_check_creates_nothing(tmp_path):
    (tmp_path / "報價#1").mkdir()
    for name in ("nope.db", "what#.db") + (() if sys.platform == "win32" else ("what?.db",)):
        assert check_integrity(tmp_path / "報價#1" / name) == {"ok": False, "schema_version": None,
                                                              "message": "檔案不存在"}
    assert _files(tmp_path) == {"報價#1"}


def test_damaged_file_check_is_read_only(tmp_path):
    bad = tmp_path / "成本資料%2026" / "bad.db"
    bad.parent.mkdir()
    bad.write_bytes(b"this is not sqlite" * 300)
    content = bad.read_bytes()
    info = check_integrity(bad)
    assert info["ok"] is False and "不是可用的案件資料庫" in info["message"]
    assert bad.read_bytes() == content
    assert _files(tmp_path) == {"成本資料%2026", "成本資料%2026/bad.db"}


def test_damaged_backup_in_special_folder_keeps_current_data(tmp_path):
    d = tmp_path / "報價#1"
    store = _populated(d / "cases.db")
    expected = _dump(store.path)
    bad = d / "壞掉的備份.db"
    bad.write_bytes(b"\x00" * 8192)
    with pytest.raises(StoreError, match="備份檔無法使用"):
        store.restore(bad, confirm=True)
    assert _dump(store.path) == expected
    assert check_integrity(store.path)["ok"]


def test_backup_vanishing_during_restore_keeps_current_data(tmp_path, monkeypatch):
    """E.g. a USB drive unplugged after the check: clear error, current data unchanged."""
    d = tmp_path / "what?"
    store = _populated(d / "cases.db")
    expected = _dump(store.path)
    gone = d / "unplugged" / "backup.db"
    monkeypatch.setattr(cs, "check_integrity", lambda p: {"ok": True, "schema_version": cs.SCHEMA_VERSION,
                                                          "message": "完整"})
    with pytest.raises(StoreError, match="還原失敗"):
        store.restore(gone, confirm=True)
    monkeypatch.undo()
    assert _dump(store.path) == expected
    assert not gone.exists() and not gone.parent.exists()


def test_full_lifecycle_backup_change_restore_is_identical(tmp_path):
    d = tmp_path / "報價 資料#2026"
    store = _populated(d / "cases.db")
    backup = store.backup(d / "backup.db")
    original = _dump(store.path)
    assert _dump(backup) == original

    # Change everything that matters after the backup.
    store.add_quote_version(CASE, "1", D("999"), D("1"), {"unit_cost": D("1")}, reason="誤植")
    record_outcome(store, CASE, "1", 2, {"result": "成交", "won_quantity": D("100"), "actual_quantity": D("100"),
                                          "actual_total_cost": D("99999")}, reason="誤植")
    store.add_case({"case_id": "X|1|v1", "customer_code": "X", "rfq_no": "1", "rfq_date": "2026-11-04",
                    "status": "待估價", "source_file": "x.xlsx"},
                   [{"line_no": "1", "product": "P", "quantity": D("1"), "unit": "pcs", "currency": "TWD"}],
                   reason="誤建")
    assert _dump(store.path) != original

    store.restore(backup, confirm=True)
    assert _dump(store.path) == original

    # Field-level checks of the restored content.
    assert [c["case_id"] for c in store.list_cases()] == sorted(
        ["C-001|RFQ-2612-001|v1", "C-001|RFQ-2612-001|v2", "00125|000045|v1", "C-002|RFQ-2612-003|v1"])
    case = store.get_case(CASE)
    assert case["status"] == "成交" and [l["line_no"] for l in case["lines"]] == ["1", "2"]
    versions = store.quote_versions(CASE, "1")
    assert [(v["version"], v["unit_price"], v["quantity"], v["cost_snapshot"]) for v in versions] == [
        (1, D("300"), D("100"), {"unit_cost": D("200")}), (2, D("310"), D("100"), {"unit_cost": D("205.5")})]
    outcomes = store.outcomes(CASE, "1", 2)
    assert len(outcomes) == 1 and outcomes[0]["data"]["result"] == "成交"
    assert outcomes[0]["data"]["actual_total_cost"] == D("22500")
    assert [(e["action"], e["old_value"], e["new_value"]) for e in store.events(CASE)] == [
        ("新增案件", None, "待估價"), ("變更狀態", "待估價", "待人工覆核"), ("變更狀態", "待人工覆核", "已產生報價草稿"),
        ("變更狀態", "已產生報價草稿", "已報價"), ("新增報價版本", None, "1#v1"), ("新增報價版本", None, "1#v2"),
        ("變更狀態", "已報價", "成交"), ("回填結果", None, "1#v2#r1")]
    assert check_integrity(store.path) == {"ok": True, "schema_version": 1, "message": "完整"}
