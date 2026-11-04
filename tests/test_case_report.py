"""PR #35: internal case audit report (6 sheets) and the separate customer draft."""

import io
from decimal import Decimal

import openpyxl
import pytest

from core.case_report import SHEETS, build_case_customer_draft, build_case_report
from core.case_store import CaseStore
from core.quote_feedback import record_outcome

D = Decimal


@pytest.fixture
def store(tmp_path):
    s = CaseStore(tmp_path / "c.db", enabled=True)
    s.initialize()
    s.add_case({"case_id": "C-001|R1|v1", "customer_code": "C-001", "rfq_no": "R1", "rfq_date": "2026-11-01",
                "status": "已報價", "source_file": "rfq.xlsx"},
               [{"line_no": "1", "product": "=HYPERLINK(\"x\")", "quantity": D("100"), "unit": "PCS", "currency": "TWD"},
                {"line_no": "2", "product": "P-2", "quantity": D("40"), "unit": "PCS", "currency": "TWD"}],
               reason="匯入")
    s.add_quote_version("C-001|R1|v1", "1", D("300"), D("100"), {"unit_cost": D("200"), "price_floor": D("250")},
                        reason="首次報價")
    record_outcome(s, "C-001|R1|v1", "1", 1, {"result": "成交", "won_quantity": D("100"), "actual_quantity": D("100"),
                                               "actual_total_cost": D("22500")}, reason="回填")
    return s


def _wb(data):
    return openpyxl.load_workbook(io.BytesIO(data))


def _rows(ws):
    return [[c for c in r] for r in ws.iter_rows(values_only=True)]


def _find(ws, header):
    rows = _rows(ws)
    i = next(n for n, r in enumerate(rows) if r and r[0] == header)
    cols = rows[i]
    return [dict(zip(cols, r)) for r in rows[i + 1:] if any(v is not None for v in r)]


def test_six_sheets_and_internal_label(store):
    wb = _wb(build_case_report(store, "C-001|R1|v1"))
    assert wb.sheetnames == SHEETS == ["Case Summary", "Quotation Snapshot", "Actual Cost", "Variance Analysis",
                                       "Exceptions", "Audit Trail"]
    for ws in wb:
        assert "內部" in str(ws["A1"].value)


def test_variance_values(store):
    wb = _wb(build_case_report(store, "C-001|R1|v1"))
    rows = {r["行號"]: r for r in _find(wb["Variance Analysis"], "行號")}
    r = rows["1"]
    assert r["狀態"] == "可分析"
    assert r["預估毛利率%"] == pytest.approx(33.33) and r["實際毛利率%"] == pytest.approx(25.0)
    assert r["成本差異"] == pytest.approx(2500) and r["毛利率下降（百分點）"] == pytest.approx(8.33)
    exc = _find(wb["Exceptions"], "行號")
    assert any(e["行號"] == "2" and "尚無報價版本" in e["說明"] for e in exc)


def test_formula_injection_is_neutralised(store):
    wb = _wb(build_case_report(store, "C-001|R1|v1"))
    for ws in wb:
        for row in ws.iter_rows():
            for c in row:
                assert c.data_type != "f"
    values = [v for r in _rows(wb["Quotation Snapshot"]) for v in r]
    assert "'=HYPERLINK(\"x\")" in values


def test_audit_trail_has_manual_actor(store):
    wb = _wb(build_case_report(store, "C-001|R1|v1"))
    events = _find(wb["Audit Trail"], "時間")
    assert [e["動作"] for e in events] == ["新增案件", "新增報價版本", "回填結果"]
    assert all(e["操作人"] == "人工填寫（未經身分驗證）" for e in events)


def test_customer_draft_has_no_internal_data(store):
    data = build_case_customer_draft(store, "C-001|R1|v1", prices_confirmed=False)
    wb = _wb(data)
    text = " ".join(str(v) for ws in wb for r in ws.iter_rows(values_only=True) for v in r if v is not None)
    for word in ("成本", "毛利", "22500", "200", "250", "底價", "實際"):
        assert word not in text
    assert "未核准草稿" in text
    assert "300" in text


def test_unknown_case(store):
    with pytest.raises(ValueError):
        build_case_report(store, "nope")
