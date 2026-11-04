"""PR #32: local SQLite case store."""

import sqlite3
from decimal import Decimal

import pytest

import core.case_store as cs
from core.case_store import (
    SCHEMA_VERSION,
    CaseStore,
    IncompatibleSchema,
    StorageDisabled,
    StoreError,
    check_integrity,
)

CASE = {"case_id": "RFQ-0001", "customer_code": "C-001", "rfq_no": "RFQ-0001", "rfq_date": "2026-12-01",
        "status": "待估價", "source_file": "rfq.xlsx"}
LINE = {"line_no": "1", "product": "P-1001", "drawing_version": "B", "quantity": Decimal("100"), "unit": "pcs",
        "currency": "TWD", "required_date": "2027-01-15", "source_row": 2}


def store(tmp_path, **kw):
    s = CaseStore(tmp_path / "cases.db", enabled=True, **kw)
    s.initialize()
    return s


def test_disabled_by_default_and_never_writes(tmp_path):
    s = CaseStore(tmp_path / "cases.db")
    assert s.enabled is False
    with pytest.raises(StorageDisabled):
        s.initialize()
    with pytest.raises(StorageDisabled):
        s.add_case(CASE, [LINE], reason="x")
    assert not (tmp_path / "cases.db").exists()


def test_path_must_be_explicit_and_local(tmp_path):
    for bad in ("", None, "\\\\server\\share\\cases.db", "//server/share/cases.db"):
        with pytest.raises(StoreError):
            CaseStore(bad, enabled=True)


def test_initialize_twice_and_schema_version(tmp_path):
    s = store(tmp_path)
    s.initialize()
    assert s.schema_version() == SCHEMA_VERSION
    with sqlite3.connect(tmp_path / "cases.db") as con:
        assert con.execute("PRAGMA journal_mode").fetchone()[0].lower() == "delete"


def test_add_case_and_read_back_with_blank_vs_zero(tmp_path):
    s = store(tmp_path)
    s.add_case(CASE, [LINE, dict(LINE, line_no="2", quantity=Decimal("0"), required_date=None)], reason="匯入 RFQ")
    case = s.get_case("RFQ-0001")
    assert case["status"] == "待估價" and len(case["lines"]) == 2
    l1, l2 = case["lines"]
    assert l1["quantity"] == Decimal("100") and l2["quantity"] == Decimal("0") and l2["required_date"] is None
    events = s.events("RFQ-0001")
    assert events[0]["action"] == "新增案件" and events[0]["reason"] == "匯入 RFQ"
    assert events[0]["actor"] == "人工填寫（未經身分驗證）"


def test_duplicate_case_id_is_rejected_not_overwritten(tmp_path):
    s = store(tmp_path)
    s.add_case(CASE, [LINE], reason="x")
    with pytest.raises(StoreError):
        s.add_case(dict(CASE, customer_code="C-999"), [LINE], reason="y")
    assert s.get_case("RFQ-0001")["customer_code"] == "C-001"


def test_unknown_fields_and_raw_bytes_are_rejected(tmp_path):
    s = store(tmp_path)
    with pytest.raises(StoreError):
        s.add_case(dict(CASE, 聯絡人電話="0912"), [LINE], reason="x")
    with pytest.raises(StoreError):
        s.add_case(CASE, [dict(LINE, raw=b"PK\x03\x04")], reason="x")
    assert s.get_case("RFQ-0001") is None


def test_transaction_rolls_back_on_failure(tmp_path, monkeypatch):
    s = store(tmp_path)
    with pytest.raises(StoreError):
        s.add_case(CASE, [LINE, dict(LINE)], reason="duplicate line")     # duplicate line_no -> constraint
    assert s.get_case("RFQ-0001") is None and s.events("RFQ-0001") == []

    def boom(*a, **k):
        raise sqlite3.OperationalError("disk I/O error")
    monkeypatch.setattr(cs, "_insert_event", boom)
    with pytest.raises(StoreError):
        s.add_case(CASE, [LINE], reason="x")
    assert s.get_case("RFQ-0001") is None


def test_quote_versions_are_appended_never_overwritten(tmp_path):
    s = store(tmp_path)
    s.add_case(CASE, [LINE], reason="x")
    snap = {"新完整成本": Decimal("872.20"), "安全底價": Decimal("1026.12"), "人工": None}
    v1 = s.add_quote_version("RFQ-0001", "1", unit_price=Decimal("1050"), quantity=Decimal("100"),
                             cost_snapshot=snap, reason="首次報價")
    v2 = s.add_quote_version("RFQ-0001", "1", unit_price=Decimal("1040"), quantity=Decimal("100"),
                             cost_snapshot=snap, reason="客戶議價")
    assert (v1, v2) == (1, 2)
    versions = s.quote_versions("RFQ-0001", "1")
    assert [v["unit_price"] for v in versions] == [Decimal("1050"), Decimal("1040")]
    assert versions[0]["cost_snapshot"] == snap
    with pytest.raises(StoreError):
        s.add_quote_version("RFQ-0001", "1", unit_price=Decimal("1"), quantity=Decimal("1"), cost_snapshot={}, reason="")
    with pytest.raises(StoreError):
        s.add_quote_version("RFQ-9999", "1", unit_price=Decimal("1"), quantity=Decimal("1"), cost_snapshot={}, reason="x")


def test_status_update_requires_reason_and_keeps_history(tmp_path):
    s = store(tmp_path)
    s.add_case(CASE, [LINE], reason="x")
    with pytest.raises(StoreError):
        s.update_case_status("RFQ-0001", "待人工覆核", reason="  ", source="UI")
    s.update_case_status("RFQ-0001", "待人工覆核", reason="成本已確認", source="UI")
    ev = s.events("RFQ-0001")[-1]
    assert (ev["old_value"], ev["new_value"], ev["reason"], ev["source"]) == ("待估價", "待人工覆核", "成本已確認", "UI")


def test_backup_restore_roundtrip(tmp_path):
    s = store(tmp_path)
    s.add_case(CASE, [LINE], reason="x")
    backup = tmp_path / "backup.db"
    s.backup(backup)
    assert check_integrity(backup)["ok"] is True
    with pytest.raises(StoreError):
        s.backup(backup)                                   # never silently overwrite a backup
    s.update_case_status("RFQ-0001", "作廢", reason="誤建", source="UI")
    with pytest.raises(StoreError):
        s.restore(backup)                                  # needs explicit confirmation
    previous = s.restore(backup, confirm=True)
    assert s.get_case("RFQ-0001")["status"] == "待估價"
    assert previous.exists() and check_integrity(previous)["ok"] is True   # pre-restore copy kept


def test_corrupted_backup_is_refused(tmp_path):
    s = store(tmp_path)
    s.add_case(CASE, [LINE], reason="x")
    bad = tmp_path / "bad.db"
    bad.write_bytes(b"SQLite format 3\x00" + b"\x00" * 50 + b"garbage" * 100)
    assert check_integrity(bad)["ok"] is False
    with pytest.raises(StoreError):
        s.restore(bad, confirm=True)
    assert s.get_case("RFQ-0001")["status"] == "待估價"


def test_incompatible_schema_is_refused(tmp_path):
    s = store(tmp_path)
    with sqlite3.connect(tmp_path / "cases.db") as con:
        con.execute("UPDATE meta SET value = ? WHERE key = 'schema_version'", (str(SCHEMA_VERSION + 1),))
    with pytest.raises(IncompatibleSchema):
        CaseStore(tmp_path / "cases.db", enabled=True).initialize()
    other = tmp_path / "other.db"
    sqlite3.connect(other).close()
    with pytest.raises(StoreError):
        s.restore(other, confirm=True)


def test_migration_from_older_version_runs_in_order(tmp_path, monkeypatch):
    s = store(tmp_path)
    with sqlite3.connect(tmp_path / "cases.db") as con:
        con.execute("UPDATE meta SET value = '0' WHERE key = 'schema_version'")
    calls = []
    monkeypatch.setitem(cs.MIGRATIONS, 0, lambda con: calls.append(0))
    CaseStore(tmp_path / "cases.db", enabled=True).initialize()
    assert calls == [0] and s.schema_version() == SCHEMA_VERSION


def test_database_files_are_git_ignored():
    from pathlib import Path
    ignore = (Path(__file__).resolve().parents[1] / ".gitignore").read_text(encoding="utf-8").splitlines()
    for pattern in ("*.db", "*.sqlite", "*.sqlite3", "case_backups/"):
        assert pattern in ignore
