"""Cost totals must reproduce the independent acceptance workbook."""

import datetime as dt
from decimal import Decimal
from pathlib import Path

import openpyxl
import pandas as pd
import pytest

from core.reader import read_bom, read_price_increase, read_sheet
from core.matcher import match_prices
from core.calculator import calculate_cost_impact

ROOT = Path(__file__).resolve().parents[1]
AS_OF = dt.date(2026, 12, 1)


@pytest.fixture
def result():
    src = ROOT / "samples" / "sample_bom.xlsx"
    b = read_bom(src).data
    p = read_price_increase(ROOT / "samples" / "sample_price_increase.xlsx").data
    details = read_sheet(src, "ProductCost", ["成品編號"]).data
    return calculate_cost_impact(match_prices(b, p, AS_OF), details)


def test_six_reference_product_totals_and_monthly_costs(result):
    wb = openpyxl.load_workbook(ROOT / "tests" / "fixtures" / "expected_result_reference.xlsx", data_only=True)
    ws = wb["Expected Numbers"]
    reference = {r[0]: r for r in list(ws.values)[1:] if r[0] is not None}
    assert len(reference) == 6
    rows = result.cost_impact.set_index("成品編號")
    assert set(rows.index) == set(reference)
    for product, expected in reference.items():
        got = rows.loc[product]
        for column, value in (("原材料成本", expected[1]), ("新材料成本", expected[2]),
                              ("成本增加", expected[3]), ("原成本", expected[4]),
                              ("新成本", expected[5]), ("預估月成本增加", expected[6])):
            assert abs(got[column] - Decimal(str(value))) <= Decimal("0.00001"), (product, column)
        assert got["試算狀態"] == "可完整試算"
        assert got["成本口徑"] == "完整估算：材料＋人工＋製費＋其他"
    assert result.summary["預估每月總成本增加"] == Decimal("61597")
    assert result.summary["受影響成品數"] == 6
    wb.close()


def test_line_audit_matches_every_row_of_independent_reference(result):
    wb = openpyxl.load_workbook(ROOT / "tests" / "fixtures" / "expected_result_reference.xlsx", data_only=True)
    values = list(wb["Line Audit"].values)
    reference = { (r[0], r[2]): r for r in values[1:] if r[0] }
    assert len(reference) == 40
    assert len(result.line_audit) == 40
    for row in result.line_audit.to_dict("records"):
        key = (row["成品編號"], row["子件料號"])
        expected = reference[key]
        assert row["配對狀態"] == expected[11]
        assert row["供應商代碼"] == expected[12]
        for column, idx in (("用量", 5), ("原單價", 6), ("試算新單價", 7),
                            ("原材料金額", 8), ("新材料金額", 9), ("單行成本差額", 10)):
            assert abs(row[column] - Decimal(str(expected[idx]))) <= Decimal("0.00001"), key
    wb.close()


def test_all_gross_margins_and_percentages_match_reference(result):
    wb = openpyxl.load_workbook(ROOT / "tests" / "fixtures" / "expected_result_reference.xlsx", data_only=True)
    ref = list(wb["Cost Impact"].values)
    expected = {r[0]: r for r in ref[1:] if r[0]}
    for got in result.cost_impact.to_dict("records"):
        row = expected[got["成品編號"]]
        for field, idx in (("成本增加百分比", 5), ("原毛利率", 6), ("新毛利率", 7)):
            assert abs(got[field] - Decimal(str(row[idx]))) <= Decimal("0.0000000001")
        assert got["需重算報價"] == row[8]
    wb.close()


def test_no_complete_nonmaterial_cost_means_no_gross_margin():
    from core.matcher import match_prices
    b = pd.DataFrame([{"excel_row": 2, "成品編號": "P-A", "成品名稱": "A", "子件料號": "M-1",
                       "子件名稱": "x", "單位": "pcs", "用量": Decimal("0.25"), "原單價": 20}], dtype=object)
    p = pd.DataFrame([{"excel_row": 2, "子件料號": "M-1", "子件名稱": "x", "單位": "pcs",
                       "幣別": "TWD", "新單價": 16, "生效日": AS_OF}], dtype=object)
    meta = pd.DataFrame([{"成品編號": "P-A", "未稅銷售單價": 100}], dtype=object)
    calc = calculate_cost_impact(match_prices(b, p, AS_OF), meta)
    row = calc.cost_impact.iloc[0]
    assert row["原材料成本"] == Decimal("5.00")
    assert row["新材料成本"] == Decimal("4.00")
    assert row["成本增加"] == Decimal("-1.00")
    assert row["原毛利率"] is None and row["新毛利率"] is None
    assert row["成本口徑"] == "僅材料成本（非完整成本）"
    assert row["需重算報價"] == "否"


def test_blocked_product_must_not_have_a_partial_total():
    b = pd.DataFrame([
        {"excel_row": 2, "成品編號": "P-A", "成品名稱": "A", "子件料號": "M-1", "子件名稱": "x", "單位": "pcs", "用量": 1, "原單價": 10},
        {"excel_row": 3, "成品編號": "P-A", "成品名稱": "A", "子件料號": "M-2", "子件名稱": "y", "單位": "pcs", "用量": 1, "原單價": 10},
        {"excel_row": 4, "成品編號": "P-B", "成品名稱": "B", "子件料號": "M-3", "子件名稱": "z", "單位": "pcs", "用量": 1, "原單價": 10},
    ], dtype=object)
    p = pd.DataFrame([
        {"excel_row": 2, "子件料號": "M-2", "子件名稱": "y", "單位": "pcs", "幣別": "TWD", "新單價": None, "生效日": AS_OF},
        {"excel_row": 3, "子件料號": "M-3", "子件名稱": "z", "單位": "pcs", "幣別": "TWD", "新單價": 12, "生效日": AS_OF},
    ], dtype=object)
    calc = calculate_cost_impact(match_prices(b, p, AS_OF))
    rows = calc.cost_impact.set_index("成品編號")
    assert rows.loc["P-A", "試算狀態"] == "試算不完整／需人工確認"
    assert rows.loc["P-A", "原成本"] is None
    assert rows.loc["P-A", "新成本"] is None
    assert rows.loc["P-A", "成本增加"] is None
    assert rows.loc["P-B", "成本增加"] == Decimal("2")
    assert calc.summary["預估每月總成本增加"] is None


def test_duplicate_product_cost_records_cannot_be_arbitrarily_selected(result):
    src = ROOT / "samples" / "sample_bom.xlsx"
    bom = read_bom(src).data
    prices = read_price_increase(ROOT / "samples" / "sample_price_increase.xlsx").data
    meta = read_sheet(src, "ProductCost", ["成品編號"]).data
    meta = pd.concat([meta, meta.iloc[[0]]], ignore_index=True)
    calc = calculate_cost_impact(match_prices(bom, prices, AS_OF), meta)
    row = calc.cost_impact.set_index("成品編號").loc["P-1001"]
    assert row["成本口徑"] == "僅材料成本（非完整成本）"
    assert row["原毛利率"] is None and row["新毛利率"] is None
    assert row["預估月成本增加"] is None
    assert calc.summary["預估每月總成本增加"] is None


def test_incomplete_fixed_cost_and_valid_sales_still_have_no_gross_margin(result):
    src = ROOT / "samples" / "sample_bom.xlsx"
    bom = read_bom(src).data
    prices = read_price_increase(ROOT / "samples" / "sample_price_increase.xlsx").data
    meta = read_sheet(src, "ProductCost", ["成品編號"]).data
    meta.loc[0, "單件人工成本"] = None
    calc = calculate_cost_impact(match_prices(bom, prices, AS_OF), meta)
    row = calc.cost_impact.set_index("成品編號").loc["P-1001"]
    assert row["原成本"] == row["原材料成本"]
    assert row["成本口徑"] == "僅材料成本（非完整成本）"
    assert row["原毛利率"] is None and row["新毛利率"] is None
