"""Adversarial end-to-end checks: hostile or messy inputs must never yield
a confident but wrong margin."""

import datetime as dt
import io
from decimal import Decimal

import openpyxl
import pandas as pd

from core.calculator import calculate_cost_impact
from core.matcher import match_prices
from core.quote_reader import QUOTE_REQUIRED_COLUMNS, read_open_quotes
from core.quote_risk import STATUS_OK, STATUS_REVIEW, STATUS_UNRELIABLE, assess_quote_risk
from core.reader import read_bom, read_price_increase, read_sheet
from core.report import build_report
from tests.test_reader import SAMPLE_BOM, SAMPLE_PRICE

AS_OF = dt.date(2026, 12, 1)
D1, D2 = dt.datetime(2026, 11, 1), dt.datetime(2027, 1, 31)


def _costs(product_cost=None):
    matched = match_prices(read_bom(SAMPLE_BOM).data, read_price_increase(SAMPLE_PRICE).data, AS_OF)
    if product_cost is None:
        product_cost = read_sheet(SAMPLE_BOM, "ProductCost", ["成品編號"]).data
    return matched, calculate_cost_impact(matched, product_cost)


def _quotes_xlsx(rows):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "OpenQuotes"
    ws.append(QUOTE_REQUIRED_COLUMNS)
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return read_open_quotes(buf.getvalue()).data


def _status(rows, **kw):
    _, costs = _costs(kw.pop("product_cost", None))
    return list(assess_quote_risk(_quotes_xlsx(rows), costs, AS_OF, **kw).risk.sort_values("來源Excel列號")["覆核狀態"])


def test_product_id_with_spaces_matches_but_other_spelling_does_not():
    rows = [["Q", "1", " P-1001 ", "C", 1000, "TWD", 50, D1, D2, "有效"],
            ["Q", "2", "p-1001", "C", 1000, "TWD", 50, D1, D2, "有效"],
            ["Q", "3", "P-1001", "C", 1000, "TWD", 50, D1, D2, " 有效 "]]
    # Surrounding spaces are trimmed; a different case is a different ID
    # (never guessed), so it cannot get a margin.
    assert _status(rows) == [STATUS_REVIEW, STATUS_UNRELIABLE, STATUS_REVIEW]


def test_price_text_with_thousands_separator_is_rejected_not_misread():
    rows = [["Q", "1", "P-1001", "C", "1,000", "TWD", 50, D1, D2, "有效"],
            ["Q", "2", "P-1001", "C", "NT$1000", "TWD", 50, D1, D2, "有效"]]
    assert _status(rows) == [STATUS_UNRELIABLE, STATUS_UNRELIABLE]


def test_duplicate_product_cost_rows_make_quote_unreliable():
    pc = read_sheet(SAMPLE_BOM, "ProductCost", ["成品編號"]).data
    pc = pd.concat([pc, pc.iloc[[0]]], ignore_index=True)  # P-1001 twice
    rows = [["Q", "1", "P-1001", "C", 1000, "TWD", 50, D1, D2, "有效"],
            ["Q", "2", "P-1002", "C", 450, "TWD", 10, D1, D2, "有效"]]
    assert _status(rows, product_cost=pc) == [STATUS_UNRELIABLE, STATUS_OK]


def test_blank_labour_cost_cell_is_not_zero():
    pc = read_sheet(SAMPLE_BOM, "ProductCost", ["成品編號"]).data.copy()
    pc.loc[pc["成品編號"] == "P-1001", "單件人工成本"] = None
    rows = [["Q", "1", "P-1001", "C", 1000, "TWD", 50, D1, D2, "有效"]]
    assert _status(rows, product_cost=pc) == [STATUS_UNRELIABLE]


def test_price_equal_to_cost_and_below_cost():
    rows = [["Q", "1", "P-1001", "C", "872.20", "TWD", 1, D1, D2, "有效"],
            ["Q", "2", "P-1001", "C", 500, "TWD", 1, D1, D2, "有效"]]
    _, costs = _costs()
    risk = assess_quote_risk(_quotes_xlsx(rows), costs, AS_OF, Decimal("0")).risk.sort_values("來源Excel列號")
    assert list(risk["新毛利率"]) == [Decimal("0"), (Decimal(500) - Decimal("872.20")) / 500]
    assert list(risk["覆核狀態"]) == [STATUS_OK, STATUS_REVIEW]


def test_formula_like_quote_fields_never_become_formulas():
    matched, costs = _costs()
    rows = [["=1+1", "@SUM(A1)", "P-1001", "+CMD", 1000, "TWD", 50, D1, D2, "有效"]]
    q = _quotes_xlsx(rows)
    # A real formula cell has no cached value -> blank -> blocking.
    risk = assess_quote_risk(q, costs, AS_OF)
    assert risk.risk.iloc[0]["覆核狀態"] == STATUS_UNRELIABLE
    wb = openpyxl.load_workbook(io.BytesIO(build_report(matched, costs, AS_OF, risk)))
    assert not [c for ws in wb for row in ws.iter_rows() for c in row if c.data_type == "f"]


def test_as_of_datetime_is_accepted_like_date():
    _, costs = _costs()
    q = _quotes_xlsx([["Q", "1", "P-1001", "C", 1000, "TWD", 50, D1, D2, "有效"]])
    a = assess_quote_risk(q, costs, dt.datetime(2026, 12, 1, 23, 59)).risk
    b = assess_quote_risk(q, costs, AS_OF).risk
    assert a.equals(b)


def test_quote_window_uses_as_of_not_today():
    _, costs = _costs()
    q = _quotes_xlsx([["Q", "1", "P-1001", "C", 1000, "TWD", 50,
                       dt.datetime(2030, 1, 1), dt.datetime(2030, 12, 31), "有效"]])
    assert assess_quote_risk(q, costs, AS_OF).risk.iloc[0]["覆核狀態"] != STATUS_REVIEW
    # For a scenario in 2030 the same quote is assessed (cost uses 2030 too).
    matched = match_prices(read_bom(SAMPLE_BOM).data, read_price_increase(SAMPLE_PRICE).data, dt.date(2030, 6, 1))
    status = assess_quote_risk(q, calculate_cost_impact(matched, read_sheet(SAMPLE_BOM, "ProductCost", ["成品編號"]).data),
                               dt.date(2030, 6, 1)).risk.iloc[0]["覆核狀態"]
    assert status == STATUS_UNRELIABLE  # BOM valid only until 2027-12-31 -> incomplete cost
