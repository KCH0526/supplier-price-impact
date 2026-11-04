"""PR #36: enterprise release-candidate acceptance (core lifecycle, migration rehearsal, docs)."""

import io
import sqlite3
from decimal import Decimal
from pathlib import Path

import openpyxl
import pytest

import core.case_store as cs
from core.case_report import SHEETS, build_case_customer_draft, build_case_report
from core.case_store import CaseStore, StoreError
from core.quote_feedback import analyze, record_outcome
from core.rfq import read_rfq, save_rfq_cases, validate_transition

ROOT = Path(__file__).resolve().parents[1]
CASE = "C-001|RFQ-2612-001|v1"
D = Decimal


def _lifecycle(tmp_path):
    store = CaseStore(tmp_path / "cases.db", enabled=True)
    store.initialize()
    assert save_rfq_cases(store, read_rfq(ROOT / "samples" / "rfq" / "rfq_sample.xlsx"), reason="RC 驗收") == 4
    for status in ("待人工覆核", "已產生報價草稿", "已報價"):
        store.update_case_status(CASE, status, reason=f"RC：{status}", validator=validate_transition)
    store.add_quote_version(CASE, "1", D("300"), D("100"), {"unit_cost": D("200")}, reason="首次報價")
    store.update_case_status(CASE, "成交", reason="客戶下單", validator=validate_transition)
    record_outcome(store, CASE, "1", 1, {"result": "成交", "won_quantity": D("100"), "actual_quantity": D("100"),
                                          "actual_total_cost": D("22500")}, reason="月結")
    return store


def test_full_lifecycle_on_the_synthetic_sample(tmp_path):
    store = _lifecycle(tmp_path)
    with pytest.raises(StoreError):
        store.update_case_status(CASE, "待估價", reason="結案後不可再改", validator=validate_transition)
    latest = store.quote_versions(CASE, "1")[-1]
    r = analyze(latest, store.outcomes(CASE, "1", 1)[-1]["data"])
    assert (r["estimated_margin_pct"], r["actual_margin_pct"], r["cost_variance"], r["margin_drop_points"]) == (
        D("33.33"), D("25.00"), D("2500"), D("8.33"))
    wb = openpyxl.load_workbook(io.BytesIO(build_case_report(store, CASE)))
    assert wb.sheetnames == SHEETS
    draft = openpyxl.load_workbook(io.BytesIO(build_case_customer_draft(store, CASE, prices_confirmed=False)))
    text = " ".join(str(v) for ws in draft for row in ws.iter_rows(values_only=True) for v in row if v is not None)
    assert "22500" not in text and "成本" not in text and "毛利" not in text
    assert [e["action"] for e in store.events(CASE)].count("變更狀態") == 4


def test_backup_then_change_then_restore(tmp_path):
    store = _lifecycle(tmp_path)
    backup = store.backup(tmp_path / "bk" / "b.db")
    record_outcome(store, CASE, "1", 1, {"result": "成交", "won_quantity": D("100"), "actual_quantity": D("100"),
                                          "actual_total_cost": D("23000")}, reason="誤植")
    assert len(store.outcomes(CASE, "1", 1)) == 2
    with pytest.raises(StoreError):
        store.restore(backup)
    previous = store.restore(backup, confirm=True)
    assert len(store.outcomes(CASE, "1", 1)) == 1
    assert len(CaseStore(previous, enabled=True).outcomes(CASE, "1", 1)) == 2


def test_migration_rehearsal_keeps_existing_data(tmp_path, monkeypatch):
    _lifecycle(tmp_path)
    monkeypatch.setattr(cs, "SCHEMA_VERSION", 2)
    monkeypatch.setitem(cs.MIGRATIONS, 1, lambda con: con.execute("ALTER TABLE cases ADD COLUMN note TEXT"))
    store = CaseStore(tmp_path / "cases.db", enabled=True)
    store.initialize()
    assert store.schema_version() == 2
    assert store.get_case(CASE)["status"] == "成交" and store.get_case(CASE)["note"] is None
    assert store.quote_versions(CASE, "1")[0]["cost_snapshot"] == {"unit_cost": D("200")}


def test_failed_migration_rolls_back(tmp_path, monkeypatch):
    _lifecycle(tmp_path)

    def broken(con):
        con.execute("ALTER TABLE cases ADD COLUMN note TEXT")
        raise RuntimeError("模擬升級失敗")
    monkeypatch.setattr(cs, "SCHEMA_VERSION", 2)
    monkeypatch.setitem(cs.MIGRATIONS, 1, broken)
    with pytest.raises(RuntimeError):
        CaseStore(tmp_path / "cases.db", enabled=True).initialize()
    with sqlite3.connect(tmp_path / "cases.db") as con:
        assert con.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0] == "1"
        assert "note" not in [r[1] for r in con.execute("PRAGMA table_info(cases)")]
        assert con.execute("SELECT status FROM cases WHERE case_id=?", (CASE,)).fetchone()[0] == "成交"


def test_rc_report_is_honest():
    text = (ROOT / "docs" / "ENTERPRISE_RC_REPORT.md").read_text(encoding="utf-8")
    for must in ("Release Candidate", "合成資料", "尚未", "人工填寫", "不支援多人", "沒有加密", "streamlit==1.66.1",
                 "pandas==3.1.0", "openpyxl==3.1.5", "Python 3.11"):
        assert must in text, must
    for forbidden in ("已通過真實 ERP", "已通過客戶驗收", "支援多使用者權限"):
        assert forbidden not in text
