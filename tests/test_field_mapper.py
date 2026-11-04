"""Tests for core.field_mapper: explicit ERP column mapping to the standard format."""

import datetime as dt
import io
import json
from decimal import Decimal
from pathlib import Path

import openpyxl
import pytest

from core.calculator import calculate_cost_impact
from core.field_mapper import (
    TARGETS,
    build_standard_workbook,
    list_sheets,
    mapping_from_json,
    mapping_to_json,
    read_source,
    standardize,
    validate_mapping,
)
from core.matcher import match_prices
from core.quote_reader import read_open_quotes
from core.quote_risk import assess_quote_risk
from core.reader import read_bom, read_price_increase, read_sheet
from core.validation import ERROR, WARNING, has_blocking

ROOT = Path(__file__).resolve().parents[1]
ERP = ROOT / "samples" / "sample_erp_export.xlsx"
CONFIG = ROOT / "samples" / "sample_field_mapping.json"
AS_OF = dt.date(2026, 12, 1)


def xlsx(sheet, header, rows):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = sheet
    ws.append(header)
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def errors(issues):
    return [i for i in issues if i.severity == ERROR]


# ---------- schema ----------

def test_targets_cover_all_standard_sheets_with_existing_required_columns():
    assert set(TARGETS) == {"BOM", "ProductCost", "PriceIncrease", "OpenQuotes", "HistoricalQuotes", "BatchCost", "RFQ"}
    assert TARGETS["BOM"].required == ["成品編號", "成品名稱", "子件料號", "子件名稱", "單位", "用量", "原單價"]
    assert TARGETS["PriceIncrease"].required == ["子件料號", "子件名稱", "單位", "幣別", "新單價", "生效日"]
    assert TARGETS["OpenQuotes"].required[:2] == ["報價單號", "行號"]
    assert TARGETS["ProductCost"].required == ["成品編號"]
    for t in TARGETS.values():
        assert not set(t.required) & set(t.optional)


# ---------- reading the source ----------

def test_list_sheets_and_preview_source():
    sheets, issues = list_sheets(ERP)
    assert issues == []
    assert {"產品結構明細", "成本資料", "供應商調價", "客戶報價單"} <= set(sheets)
    src = read_source(ERP.read_bytes(), "產品結構明細")
    assert src.issues == []
    assert "主件品號" in src.headers and "建檔人員" in src.headers
    assert len(src.data) == 40


def test_list_sheets_of_a_broken_file_is_blocking():
    sheets, issues = list_sheets(b"not a workbook")
    assert sheets == [] and has_blocking(issues)


def test_duplicate_source_headers_are_blocking():
    src = read_source(xlsx("S", ["品號", "品號", "數量"], [["A", "B", 1]]), "S")
    assert src.data is None and has_blocking(src.issues)


# ---------- validating a mapping ----------

HEADERS = ["品號", "品名", "元件", "元件名", "單位", "用量", "單價", "備註"]
GOOD = {"成品編號": "品號", "成品名稱": "品名", "子件料號": "元件", "子件名稱": "元件名",
        "單位": "單位", "用量": "用量", "原單價": "單價"}


def test_complete_mapping_is_valid():
    assert validate_mapping("BOM", GOOD, HEADERS) == []


def test_missing_required_target_is_blocking():
    columns = dict(GOOD)
    del columns["原單價"]
    issues = validate_mapping("BOM", columns, HEADERS)
    assert [(i.column, i.severity) for i in issues] == [("原單價", ERROR)]


def test_same_source_column_used_twice_is_blocking():
    columns = dict(GOOD, 子件名稱="品名")
    issues = errors(validate_mapping("BOM", columns, HEADERS))
    assert len(issues) == 1 and "品名" in issues[0].reason and "重複" in issues[0].reason


def test_unknown_source_or_target_column_is_blocking():
    assert errors(validate_mapping("BOM", dict(GOOD, 原單價="不存在"), HEADERS))
    assert errors(validate_mapping("BOM", dict(GOOD, 自創欄位="備註"), HEADERS))
    with pytest.raises(ValueError):
        validate_mapping("Unknown", GOOD, HEADERS)


def test_blank_selection_counts_as_unmapped():
    issues = validate_mapping("BOM", dict(GOOD, 原單價=None, 工廠代碼=""), HEADERS)
    assert [i.column for i in errors(issues)] == ["原單價"]


# ---------- standardising ----------

def _standardize(header, rows, columns, target="BOM"):
    src = read_source(xlsx("S", header, rows), "S")
    return standardize(target, src.data, columns)


def test_values_are_copied_verbatim_blank_stays_blank():
    df, issues = _standardize(HEADERS, [["P-1", "成品", "M-1", "料", "kg", None, 12.5, "x"]], GOOD)
    rec = df.iloc[0]
    assert rec["用量"] is None            # never filled with 0
    assert rec["原單價"] == 12.5
    assert rec["單位"] == "kg"            # never converted
    assert "備註" not in df.columns       # unmapped columns are not copied
    assert rec["來源Excel列號"] == 2
    assert errors(issues) == []


def test_text_leading_zeros_kept_numeric_ids_warned_not_padded():
    rows = [["000123", "成品", 45, "料", "pcs", 1, 1, ""], ["0042", "成品", "M-2", "料", "pcs", 1, 1, ""]]
    df, issues = _standardize(HEADERS, rows, GOOD)
    assert list(df["成品編號"]) == ["000123", "0042"]
    assert list(df["子件料號"]) == ["45", "M-2"]   # converted to text, not zero-padded
    warns = [i for i in issues if i.severity == WARNING]
    assert len(warns) == 1 and warns[0].column == "子件料號" and "前導零" in warns[0].reason


def test_standardize_refuses_an_invalid_mapping():
    with pytest.raises(ValueError):
        _standardize(HEADERS, [["P", "n", "M", "m", "pcs", 1, 1, ""]], dict(GOOD, 子件名稱="品名"))


# ---------- config JSON ----------

def test_config_round_trip():
    targets = {"BOM": {"source_sheet": "S", "columns": GOOD}}
    loaded = mapping_from_json(mapping_to_json(targets))
    assert loaded == targets


@pytest.mark.parametrize("text", [
    "not json",
    json.dumps({"format": "other", "version": 1, "targets": {}}),
    json.dumps({"format": "supplier-quote-margin-guard.field-mapping", "version": 99, "targets": {}}),
    json.dumps({"format": "supplier-quote-margin-guard.field-mapping", "version": 1,
                "targets": {"BOM": {"source_sheet": "S", "columns": {"成品編號": 123}}}}),
    json.dumps({"format": "supplier-quote-margin-guard.field-mapping", "version": 1,
                "targets": {"Hack": {"source_sheet": "S", "columns": {}}}}),
])
def test_invalid_config_is_rejected(text):
    with pytest.raises(ValueError):
        mapping_from_json(text)


def test_oversized_config_is_rejected():
    with pytest.raises(ValueError):
        mapping_from_json("{" + " " * 2_000_000 + "}")


# ---------- end to end: ERP-style export -> standard file -> same results ----------

def _standard_from_sample_erp():
    targets = mapping_from_json(CONFIG.read_text(encoding="utf-8"))
    frames = {}
    for target, cfg in targets.items():
        src = read_source(ERP.read_bytes(), cfg["source_sheet"])
        assert src.issues == []
        assert validate_mapping(target, cfg["columns"], src.headers) == []
        frames[target], issues = standardize(target, src.data, cfg["columns"])
        assert errors(issues) == []
    return build_standard_workbook(frames)


def test_erp_export_maps_to_identical_results():
    content = _standard_from_sample_erp()
    bom, price, quotes = read_bom(content), read_price_increase(content), read_open_quotes(content)
    assert bom.issues == price.issues == quotes.issues == []
    matched = match_prices(bom.data, price.data, AS_OF)
    costs = calculate_cost_impact(matched, read_sheet(content, "ProductCost", ["成品編號"]).data)
    assert costs.summary["預估每月總成本增加"] == Decimal("61597.00")
    p1001 = costs.cost_impact.set_index("成品編號").loc["P-1001"]
    assert (p1001["原成本"], p1001["新成本"]) == (Decimal("836.60"), Decimal("872.20"))
    risk = assess_quote_risk(quotes.data, costs, AS_OF)
    assert (risk.summary["需人工覆核"], risk.summary["尚符合設定底線"], risk.summary["不納入試算"]) == (3, 4, 1)
    a = risk.risk[risk.risk["報價單號"] == "SQ-2611-001"].iloc[0]
    assert a["維持底線所需最低單價"] == Decimal("1026.12")
    assert list(matched.exceptions["子件料號"]) == ["M-999"]


def test_standard_workbook_has_text_ids_and_no_formulas():
    header = HEADERS
    rows = [['=HYPERLINK("http://example.invalid")', "成品", "M-1", "料", "pcs", 1, 1, ""]]
    src = read_source(xlsx("S", header, rows), "S")
    # openpyxl wrote a real formula -> blank on read; use a text "=" value instead
    src.data.loc[0, "品號"] = '=HYPERLINK("http://example.invalid")'
    df, _ = standardize("BOM", src.data, GOOD)
    wb = openpyxl.load_workbook(io.BytesIO(build_standard_workbook({"BOM": df})))
    ws = wb["BOM"]
    assert [c.data_type for c in ws[2]][0] == "s"
    assert not [c for row in ws.iter_rows() for c in row if c.data_type == "f"]
    assert ws.cell(2, 1).number_format == "@"
    assert read_bom(build_standard_workbook({"BOM": df})).data.iloc[0]["成品編號"].startswith("=HYPERLINK")
