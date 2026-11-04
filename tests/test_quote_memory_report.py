"""PR #19: internal quote recommendation workbook."""

import datetime as dt
import io

import openpyxl

from core.quote_advisor import INTERNAL_LABEL, advise_quote
from core.quote_memory_report import SHEETS, build_quote_memory_report
from core.quote_search import search_similar_quotes
from tests.test_quote_advisor import INCREASE, _costs
from tests.test_quote_search import HIST, HistoricalSource, import_historical_quotes, json


def _import():
    sources = []
    for name, file in (("sales_dept", "historical_quotes_sales_dept.xlsx"),
                       ("legacy_system", "historical_quotes_legacy_system.xlsx")):
        m = json.loads((HIST / f"mapping_{name}.json").read_text(encoding="utf-8"))["targets"]["HistoricalQuotes"]
        sources.append(HistoricalSource(file, (HIST / file).read_bytes(), m["source_sheet"], m["columns"]))
    return import_historical_quotes(sources)


def _report(product_cost=True, mutate=None):
    imp = _import()
    if mutate:
        mutate(imp.records)
    search = search_similar_quotes(imp.records, "P-1001", 60, dt.date(2026, 12, 15), "pcs", drawing_version="B")
    advice = advise_quote(search, imp.records, _costs(product_cost), "0.15", price_increase_date=INCREASE)
    return openpyxl.load_workbook(io.BytesIO(build_quote_memory_report(advice, imp)), data_only=True), advice


def _rows(ws, header_row=3):
    header = [c.value for c in ws[header_row]]
    return [dict(zip(header, r)) for r in ws.iter_rows(min_row=header_row + 1, values_only=True)]


def test_sheets_and_internal_label_everywhere():
    wb, _ = _report()
    assert wb.sheetnames == SHEETS == ["Summary", "Quote Recommendation", "Historical Evidence",
                                       "Price Exceptions", "Data Quality"]
    for ws in wb:
        assert INTERNAL_LABEL in str(ws["A1"].value)
    assert "不可提供給客戶" in str(wb["Historical Evidence"]["A1"].value)


def test_recommendation_values_are_traceable():
    wb, advice = _report()
    rec = dict((r[0], r[1]) for r in wb["Quote Recommendation"].iter_rows(min_row=3, values_only=True))
    assert rec["覆核狀態"] == "歷史價格低於安全底線"
    assert rec["安全底價"] == 1026.12 and rec["新完整成本"] == 872.2
    assert "872.20 ÷ (1 − 0.15)" in rec["安全底價計算式"]
    assert rec["歷史中位數"] == 1050 and rec["可比較筆數"] == 3


def test_evidence_lists_included_and_excluded_with_sources():
    wb, _ = _report()
    rows = _rows(wb["Historical Evidence"])
    assert len(rows) == 11  # all P-1001 quotes after de-duplication, included and excluded
    assert {r["判定"] for r in rows} == {"選入", "排除"}
    assert all(r["原因"] and r["來源檔案"] and r["來源Excel列號"] for r in rows)


def test_price_exceptions_and_data_quality():
    wb, advice = _report()
    warns = _rows(wb["Price Exceptions"])
    assert len(warns) == len(advice.warnings) >= 3
    assert {"歷史價格低於安全底線", "材料漲價後仍沿用舊價"} <= {w["類型"] for w in warns}
    dq = dict((r[0], r[1]) for r in wb["Data Quality"].iter_rows(min_row=3, max_row=8, values_only=True))
    assert dq["匯入筆數"] == 15 and dq["重複略過筆數"] == 1


def test_no_floor_is_blank_not_zero():
    wb, _ = _report(product_cost=False)
    rec = dict((r[0], r[1]) for r in wb["Quote Recommendation"].iter_rows(min_row=3, values_only=True))
    assert rec["覆核狀態"] == "無法提供安全底價" and rec["安全底價"] is None


def test_no_formulas_from_historical_text():
    def mutate(df):
        df.loc[df.index[0], "客戶代碼"] = '=HYPERLINK("http://example.invalid")'
        df.loc[df["成品編號"] == "P-1001", "備註"] = "@SUM(A1)"
    wb, _ = _report(mutate=mutate)
    content = io.BytesIO()
    wb.save(content)
    raw = openpyxl.load_workbook(io.BytesIO(content.getvalue()))
    assert not [c for ws in raw for row in ws.iter_rows() for c in row if c.data_type == "f"]
