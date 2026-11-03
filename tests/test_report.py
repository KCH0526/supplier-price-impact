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
