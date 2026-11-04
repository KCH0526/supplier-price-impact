"""PR #37: failure and recovery behaviour for local deployment (no new features)."""

import sqlite3
from decimal import Decimal
from pathlib import Path

import pytest

import core.case_store as cs
from core.case_store import CaseStore, StoreError

ROOT = Path(__file__).resolve().parents[1]
CASE = {"case_id": "C1", "customer_code": "C-001", "rfq_no": "R1", "rfq_date": "2026-11-01", "status": "待估價",
        "source_file": "x.xlsx"}
LINE = {"line_no": "1", "product": "P-1", "quantity": Decimal("100"), "unit": "pcs", "currency": "TWD"}


def _store(tmp_path):
    s = CaseStore(tmp_path / "cases.db", enabled=True)
    s.initialize()
    s.add_case(CASE, [LINE], reason="建立")
    return s


def test_damaged_database_gives_a_clear_error_and_is_not_modified(tmp_path):
    bad = tmp_path / "cases.db"
    bad.write_bytes(b"not a database" * 100)
    before = bad.read_bytes()
    with pytest.raises(StoreError, match="無法開啟資料庫"):
        CaseStore(bad, enabled=True).initialize()
    assert bad.read_bytes() == before


def test_folder_as_database_path_gives_a_clear_error(tmp_path):
    with pytest.raises(StoreError, match="無法開啟資料庫"):
        CaseStore(tmp_path, enabled=True).initialize()


def test_disk_full_during_write_rolls_back(tmp_path, monkeypatch):
    s = _store(tmp_path)
    connect = CaseStore._connect

    def full(self):
        con = connect(self)
        pages = con.execute("PRAGMA page_count").fetchone()[0]
        con.execute(f"PRAGMA max_page_count = {pages}")   # simulates "database or disk is full"
        return con
    monkeypatch.setattr(CaseStore, "_connect", full)
    big = [dict(LINE, line_no=str(i), product="P" * 2000) for i in range(200)]
    with pytest.raises(StoreError, match="已復原"):
        s.add_case(dict(CASE, case_id="C2"), big, reason="大量明細")
    monkeypatch.undo()
    assert [c["case_id"] for c in s.list_cases()] == ["C1"]


def test_backup_to_unwritable_place_gives_a_clear_error(tmp_path, monkeypatch):
    s = _store(tmp_path)

    def denied(*a, **k):
        raise PermissionError("Permission denied")
    monkeypatch.setattr(Path, "mkdir", denied)
    with pytest.raises(StoreError, match="無法建立備份"):
        s.backup(tmp_path / "no" / "b.db")


def test_failed_backup_leaves_no_partial_file(tmp_path, monkeypatch):
    s = _store(tmp_path)
    dest = tmp_path / "b.db"

    class Broken:
        def __init__(self, con):
            self.con = con

        def backup(self, *a, **k):
            raise sqlite3.OperationalError("database or disk is full")

        def close(self):
            self.con.close()
    connect = CaseStore._connect
    monkeypatch.setattr(CaseStore, "_connect", lambda self: Broken(connect(self)))
    with pytest.raises(StoreError, match="無法建立備份"):
        s.backup(dest)
    assert not dest.exists()


def test_damaged_backup_is_refused_and_current_data_kept(tmp_path):
    s = _store(tmp_path)
    bad = tmp_path / "bad_backup.db"
    bad.write_bytes(b"\x00" * 4096)
    with pytest.raises(StoreError, match="備份檔無法使用"):
        s.restore(bad, confirm=True)
    assert [c["case_id"] for c in s.list_cases()] == ["C1"]


def test_newer_database_version_is_refused(tmp_path):
    s = _store(tmp_path)
    with sqlite3.connect(s.path) as con:
        con.execute("UPDATE meta SET value = ? WHERE key = 'schema_version'", (str(cs.SCHEMA_VERSION + 1),))
    with pytest.raises(StoreError, match="請更新程式"):
        CaseStore(s.path, enabled=True).initialize()


def test_page_shows_error_instead_of_crashing_on_damaged_database(tmp_path):
    pytest.importorskip("streamlit")
    from streamlit.testing.v1 import AppTest
    bad = tmp_path / "cases.db"
    bad.write_bytes(b"not a database" * 100)
    app = AppTest.from_file(str(ROOT / "pages" / "4_案件工作台.py"), default_timeout=30).run()
    app.checkbox(key="store_enabled").check().run()
    app.text_input(key="db_path").set_value(str(bad)).run()
    assert not app.exception
    assert any("無法開啟資料庫" in e.value for e in app.error)
