"""Exported workbook must be auditable and must not conceal blockers."""

import datetime as dt
from io import BytesIO
from pathlib import Path

import openpyxl
import pandas as pd

from core.calculator import calculate_cost_impact
from core.matcher import match_prices
from core.reader import read_bom, read_price_increase, read_sheet
from core.report import build_report

ROOT = Path(__file__).resolve().parents[1]
AS_OF = dt.date(2026, 12, 1)


def _samples():
    src = ROOT / "samples" / "sample_bom.xlsx"
    matched = match_prices(read_bom(src).data,
                           read_price_increase(ROOT / "samples" / "sample_price_increase.xlsx").data, AS_OF)
    cost = calculate_cost_impact(matched, read_sheet(src, "ProductCost", ["成品編號"]).data)
    return matched, cost


def test_report_has_four_sheets_and_expected_numbers():
    matched, costs = _samples()
    content = build_report(matched, costs, AS_OF)
    assert content[:2] == b"PK"
    wb = openpyxl.load_workbook(BytesIO(content), data_only=True)
    assert wb.sheetnames == ["Summary", "Cost Impact", "Exceptions", "Line Audit"]
    assert wb["Cost Impact"].max_row == 7
    assert wb["Exceptions"].max_row == 2
    assert wb["Line Audit"].max_row == 41
    impact = wb["Cost Impact"]
    headers = [c.value for c in impact[1]]
    assert "成本增加" in headers and "試算狀態" in headers
    row = {h: c.value for h, c in zip(headers, impact[2])}
    assert row["成品編號"] == "P-1001"
    assert row["原成本"] == 836.6
    assert row["新成本"] == 872.2
    assert row["成本增加"] == 35.6
    assert row["預估月成本增加"] == 14240
    assert impact.cell(2, headers.index("原毛利率") + 1).number_format == "0.00%"
    summary = dict(wb["Summary"].values)
    assert summary["試算基準日"] == "2026-12-01"
    assert summary["預估每月總成本增加（TWD）"] == 61597
    exceptions = list(wb["Exceptions"].values)
    assert "M-999" in exceptions[1]
    wb.close()


def test_blocking_exception_export_does_not_replace_unknown_totals_with_zero():
    b = pd.DataFrame([{"excel_row": 2, "成品編號": "P-A", "成品名稱": "A", "子件料號": "M-1",
                       "子件名稱": "X", "單位": "pcs", "用量": 1, "原單價": 10}], dtype=object)
    p = pd.DataFrame([{"excel_row": 2, "子件料號": "M-1", "子件名稱": "X", "單位": "kg",
                       "幣別": "TWD", "新單價": 12, "生效日": AS_OF}], dtype=object)
    matched = match_prices(b, p, AS_OF)
    content = build_report(matched, calculate_cost_impact(matched), AS_OF)
    wb = openpyxl.load_workbook(BytesIO(content), data_only=True)
    headers = [c.value for c in wb["Cost Impact"][1]]
    row = {h: c.value for h, c in zip(headers, wb["Cost Impact"][2])}
    assert row["試算狀態"] == "試算不完整／需人工確認"
    assert row["原成本"] is None and row["新成本"] is None
    assert row["成本增加"] is None
    assert wb["Exceptions"].max_row >= 2
    wb.close()


def test_user_content_cannot_become_excel_formula():
    b = pd.DataFrame([{"excel_row": 2, "成品編號": "P-A", "成品名稱": '=HYPERLINK("evil")',
                       "子件料號": "M-1", "子件名稱": "X", "單位": "pcs", "用量": 1, "原單價": 10}], dtype=object)
    p = pd.DataFrame([{"excel_row": 2, "子件料號": "M-1", "子件名稱": "X", "單位": "pcs",
                       "幣別": "TWD", "新單價": 12, "生效日": AS_OF}], dtype=object)
    matched = match_prices(b, p, AS_OF)
    wb = openpyxl.load_workbook(BytesIO(build_report(matched, calculate_cost_impact(matched), AS_OF)))
    cell = wb["Cost Impact"]["B2"]
    assert cell.data_type != "f"
    assert cell.value.startswith("'")
    wb.close()


# ---------- Quote Risk sheets (PR #9) ----------

from decimal import Decimal  # noqa: E402

from core.quote_reader import read_open_quotes  # noqa: E402
from core.quote_risk import assess_quote_risk  # noqa: E402


def _quote_report(quote_path=ROOT / "samples" / "sample_open_quotes.xlsx", floor=Decimal("0.15")):
    matched, costs = _samples()
    risk = assess_quote_risk(read_open_quotes(quote_path).data, costs, AS_OF, floor)
    return openpyxl.load_workbook(BytesIO(build_report(matched, costs, AS_OF, risk)), data_only=True)


def test_report_with_quotes_has_six_sheets_in_order():
    wb = _quote_report()
    assert wb.sheetnames == ["Summary", "Cost Impact", "Exceptions", "Line Audit", "Quote Risk", "Quote Exceptions"]


def test_quote_risk_sheet_columns_order_and_case_a():
    ws = _quote_report()["Quote Risk"]
    headers = [c.value for c in ws[1]]
    for col in ("客戶代碼", "報價單號", "行號", "成品編號", "未稅報價單價", "報價數量", "原完整成本",
                "新完整成本", "原毛利率", "新毛利率", "毛利率下降百分點", "報價情境成本增加",
                "設定毛利率底線", "維持底線所需最低單價", "覆核狀態", "問題原因", "來源Excel列號"):
        assert col in headers, col
    rows = [dict(zip(headers, r)) for r in ws.iter_rows(min_row=2, values_only=True)]
    assert len(rows) == 8
    assert [r["覆核狀態"] for r in rows[:3]] == ["需人工覆核"] * 3
    assert all(r["問題原因"] for r in rows)
    a = next(r for r in rows if r["成品編號"] == "P-1001" and r["客戶代碼"] == "C-001")
    assert a["維持底線所需最低單價"] == 1026.12
    assert a["報價情境成本增加"] == 1780
    assert round(a["原毛利率"], 4) == 0.1634 and round(a["新毛利率"], 4) == 0.1278
    assert a["設定毛利率底線"] == 0.15
    assert a["來源Excel列號"] == 2
    col = headers.index("新毛利率") + 1
    assert ws.cell(2, col).number_format == "0.00%"
    lz = next(r for r in rows if r["客戶代碼"] == "00125")
    assert isinstance(lz["客戶代碼"], str)


def test_min_price_is_not_rounded_down_in_export():
    ws = _quote_report(floor=Decimal("0.10"))["Quote Risk"]
    headers = [c.value for c in ws[1]]
    rows = [dict(zip(headers, r)) for r in ws.iter_rows(min_row=2, values_only=True)]
    a = next(r for r in rows if r["成品編號"] == "P-1001" and r["客戶代碼"] == "C-001")
    assert a["維持底線所需最低單價"] == 969.12


def test_quote_summary_and_scenario_wording():
    summary = dict(_quote_report()["Summary"].values)
    assert summary["客戶報價：需人工覆核"] == 3
    assert summary["客戶報價：最低毛利率底線"] == "15.00%"
    assert summary["報價情境成本增加合計（TWD）"] == 6480.5
    assert "不是已確認訂單量" in summary["情境金額說明"]


def test_quote_exceptions_sheet_lists_edge_problems():
    wb = _quote_report(ROOT / "tests" / "fixtures" / "test_open_quotes_edge_cases.xlsx")
    ws = wb["Quote Exceptions"]
    headers = [c.value for c in ws[1]]
    rows = [dict(zip(headers, r)) for r in ws.iter_rows(min_row=2, values_only=True)]
    kinds = {r["類型"] for r in rows}
    assert {"報價資料無效", "報價不納入試算", "報價尚未生效", "報價已過期", "成品不存在於 BOM"} <= kinds
    assert all(r["原因"] for r in rows)


def test_quote_sheets_have_no_formulas():
    matched, costs = _samples()
    q = read_open_quotes(ROOT / "samples" / "sample_open_quotes.xlsx").data
    q.loc[0, "客戶代碼"] = '=HYPERLINK("http://example.invalid","x")'
    risk = assess_quote_risk(q, costs, AS_OF)
    wb = openpyxl.load_workbook(BytesIO(build_report(matched, costs, AS_OF, risk)))
    assert [c.coordinate for ws in wb for row in ws.iter_rows() for c in row if c.data_type == "f"] == []
