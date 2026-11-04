"""PR #24: quote revision comparison (spec section 5)."""

import datetime as dt
import io
import json
from decimal import Decimal
from pathlib import Path

import openpyxl
import pytest

from core.historical_quotes import HIST_REQUIRED, HistoricalSource, import_historical_quotes
from core.quote_versions import ORDER_UNKNOWN, ORDER_OK, compare_quote_versions

ROOT = Path(__file__).resolve().parents[1]
HIST = ROOT / "samples" / "historical"


@pytest.fixture(scope="module")
def records():
    m = json.loads((HIST / "mapping_sales_dept.json").read_text(encoding="utf-8"))["targets"]["HistoricalQuotes"]
    file = HIST / "historical_quotes_sales_dept.xlsx"
    sales = HistoricalSource(file.name, file.read_bytes(), m["source_sheet"], m["columns"])
    edge = ROOT / "tests" / "fixtures" / "historical_quotes_edge_cases.xlsx"
    return import_historical_quotes([sales, HistoricalSource(edge.name, edge.read_bytes(), "HistoricalQuotes")]).records


def _synthetic(rows):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "HistoricalQuotes"
    ws.append(HIST_REQUIRED + ["報價版本"])
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return import_historical_quotes([HistoricalSource("v.xlsx", buf.getvalue(), "HistoricalQuotes")]).records


def field(result, name):
    return next(r for r in result.rows.to_dict("records") if r["欄位"] == name)


def test_price_decrease_between_revisions(records):
    r = compare_quote_versions(records, "Q-2603-007", "1", "1", "2")
    assert r.status == ORDER_OK and (r.older["報價版本"], r.newer["報價版本"]) == ("1", "2")
    price = field(r, "報價單價")
    assert (price["舊值"], price["新值"], price["差額"], price["差異百分比"]) == (
        Decimal("1000"), Decimal("990"), Decimal("-10"), Decimal("-1.00"))
    amount = field(r, "未稅金額")
    assert (amount["舊值"], amount["新值"], amount["差額"]) == (Decimal("60000"), Decimal("59400"), Decimal("-600"))
    assert field(r, "成交狀態")["新值"] == "成交" and field(r, "成交狀態")["舊值"] == "未知"
    assert "未提供" in field(r, "變更原因（人工輸入）")["新值"]
    assert r.sources["舊"]["來源Excel列號"] == 4 and r.sources["新"]["來源Excel列號"] == 5


def test_order_follows_dates_not_the_order_given(records):
    r = compare_quote_versions(records, "Q-2603-007", "1", "2", "1")
    assert (r.older["報價版本"], r.newer["報價版本"]) == ("1", "2")


def test_manual_reason_is_shown_not_invented(records):
    r = compare_quote_versions(records, "Q-2603-007", "1", "1", "2", change_reason="客戶要求加大數量後議價")
    assert field(r, "變更原因（人工輸入）")["新值"] == "客戶要求加大數量後議價"


def test_same_day_revisions_need_explicit_order(records):
    r = compare_quote_versions(records, "E-008", "1", "A", "B")
    assert r.status == ORDER_UNKNOWN and r.older is None
    assert field(r, "報價單價")["差額"] is None
    assert "無法判定" in r.message
    confirmed = compare_quote_versions(records, "E-008", "1", "A", "B", newer="B")
    p = field(confirmed, "報價單價")
    assert confirmed.status == ORDER_OK and (p["差額"], p["差異百分比"]) == (Decimal("20"), Decimal("2.00"))
    assert "使用者確認" in confirmed.message


def test_quantity_change_blocks_unit_price_comparison():
    recs = _synthetic([["Q", "1", dt.datetime(2026, 1, 1), "C", "P", 100, "pcs", "TWD", 50, "未稅", "1"],
                       ["Q", "1", dt.datetime(2026, 2, 1), "C", "P", 500, "pcs", "TWD", 45, "未稅", "2"]])
    r = compare_quote_versions(recs, "Q", "1", "1", "2")
    price = field(r, "報價單價")
    assert price["差額"] is None and "數量不同" in price["說明"]
    amount = field(r, "未稅金額")
    assert (amount["舊值"], amount["新值"], amount["差額"]) == (Decimal("5000"), Decimal("22500"), Decimal("17500"))
    assert field(r, "報價數量")["差額"] == Decimal("400")


@pytest.mark.parametrize("change, reason", [
    ({"幣別": "USD"}, "幣別"), ({"計價單位": "set"}, "計價單位"), ({"稅別": "含稅"}, "稅別")])
def test_currency_unit_tax_changes_block_price_comparison(change, reason):
    base = {"幣別": "TWD", "計價單位": "pcs", "稅別": "未稅"}
    new = dict(base, **change)
    recs = _synthetic([["Q", "1", dt.datetime(2026, 1, 1), "C", "P", 100, "pcs", "TWD", 50, "未稅", "1"],
                       ["Q", "1", dt.datetime(2026, 2, 1), "C", "P", 100, new["計價單位"], new["幣別"], 48, new["稅別"], "2"]])
    r = compare_quote_versions(recs, "Q", "1", "1", "2")
    assert field(r, "報價單價")["差額"] is None and reason in field(r, "報價單價")["說明"]


def test_missing_values_are_shown_as_blank(records):
    r = compare_quote_versions(records, "Q-2603-007", "1", "1", "2")
    material = field(r, "材質")
    assert material["舊值"] == material["新值"] == "AL6063" and material["說明"] == "相同"


def test_unknown_version_or_same_version_is_rejected(records):
    with pytest.raises(ValueError):
        compare_quote_versions(records, "Q-2603-007", "1", "1", "9")
    with pytest.raises(ValueError):
        compare_quote_versions(records, "Q-2603-007", "1", "1", "1")
    with pytest.raises(ValueError):
        compare_quote_versions(records, "E-008", "1", "A", "B", newer="C")
