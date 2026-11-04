"""PR #16: historical quote import and standardisation (spec section 4)."""

import datetime as dt
import io
import json
from pathlib import Path

import openpyxl

import core.historical_quotes as hq
from core.field_mapper import TARGETS
from core.historical_quotes import (
    HIST_OPTIONAL,
    HIST_REQUIRED,
    HistoricalSource,
    build_historical_workbook,
    import_historical_quotes,
)
from core.validation import ERROR, WARNING

ROOT = Path(__file__).resolve().parents[1]
HIST = ROOT / "samples" / "historical"
SALES = HIST / "historical_quotes_sales_dept.xlsx"
LEGACY = HIST / "historical_quotes_legacy_system.xlsx"
EDGE = ROOT / "tests" / "fixtures" / "historical_quotes_edge_cases.xlsx"


def _mapping(name):
    doc = json.loads((HIST / f"mapping_{name}.json").read_text(encoding="utf-8"))
    return doc["targets"]["HistoricalQuotes"]


def sales():
    m = _mapping("sales_dept")
    return HistoricalSource(SALES.name, SALES.read_bytes(), m["source_sheet"], m["columns"])


def legacy():
    m = _mapping("legacy_system")
    return HistoricalSource(LEGACY.name, LEGACY.read_bytes(), m["source_sheet"], m["columns"])


def edge():
    return HistoricalSource(EDGE.name, EDGE.read_bytes(), "HistoricalQuotes")


def errors(result):
    return [i for i in result.issues if i.severity == ERROR]


def rec(result, quote_no, line="1", version=None):
    df = result.records
    sel = df[(df["報價單號"] == quote_no) & (df["報價行號"] == line)]
    if version is not None:
        sel = sel[sel["報價版本"] == version]
    assert len(sel) == 1, (quote_no, line, version, len(sel))
    return sel.iloc[0]


# ---------- schema ----------

def test_schema_matches_spec_and_is_a_field_mapper_target():
    assert HIST_REQUIRED == ["報價單號", "報價行號", "報價日期", "客戶代碼", "成品編號", "報價數量",
                             "計價單位", "幣別", "報價單價", "稅別"]
    assert {"報價版本", "成品名稱", "規格圖面版次", "材質", "製程類別", "報價狀態", "成交狀態", "交期", "備註"} == set(HIST_OPTIONAL)
    assert TARGETS["HistoricalQuotes"].required == HIST_REQUIRED


# ---------- 1-4: normal imports with different names and orders ----------

def test_1_single_file_import():
    r = import_historical_quotes([sales()])
    assert errors(r) == []
    assert len(r.records) == 10
    first = rec(r, "Q-2501-001")
    assert first["來源檔案"] == SALES.name and first["來源工作表"] == "報價紀錄" and first["來源Excel列號"] == 2
    assert first["報價單價"] == 950 and first["成交狀態"] == "成交"


def test_2_3_4_multi_file_with_different_names_and_order():
    r = import_historical_quotes([sales(), legacy()])
    assert errors(r) == []
    assert len(r.records) == 15  # 16 rows, Q-2609-021/2 exported by both systems
    b = rec(r, "Q-2612-002")
    assert b["來源檔案"] == LEGACY.name and b["報價日期"].date() == dt.date(2026, 12, 10)
    assert b["報價單價"] == 1050 and b["稅別"] == "未稅" and b["成交狀態"] == "未知"
    assert r.summary["檔案數"] == 2 and r.summary["讀取列數"] == 16 and r.summary["匯入筆數"] == 15


# ---------- 5: duplicate import ----------

def test_5_same_rows_from_two_systems_are_deduplicated_not_conflicts():
    r = import_historical_quotes([sales(), legacy()])
    kept = rec(r, "Q-2609-021", "2")
    assert kept["來源檔案"] == SALES.name          # first one wins
    dup = [i for i in r.issues if "重複匯入" in i.reason]
    assert len(dup) == 1 and dup[0].severity == WARNING


def test_5_importing_the_same_file_twice_keeps_one_copy():
    r = import_historical_quotes([sales(), sales()])
    assert errors(r) == [] and len(r.records) == 10
    assert r.summary["重複略過筆數"] == 10


def test_5_reimport_of_standardized_file_keeps_original_source():
    first = import_historical_quotes([sales(), legacy()])
    content = build_historical_workbook(first.records)
    again = import_historical_quotes([HistoricalSource("standardized.xlsx", content, "HistoricalQuotes")])
    assert errors(again) == [] and len(again.records) == 15
    assert rec(again, "Q-2612-002")["來源檔案"] == LEGACY.name
    both = import_historical_quotes([HistoricalSource("standardized.xlsx", content, "HistoricalQuotes"), legacy()])
    assert len(both.records) == 15


# ---------- 6-7: versions and lines ----------

def test_6_revisions_are_kept_and_latest_is_marked():
    r = import_historical_quotes([sales()])
    v1, v2 = rec(r, "Q-2603-007", version="1"), rec(r, "Q-2603-007", version="2")
    assert (v1["報價單價"], v2["報價單價"]) == (1000, 990)
    assert v1["最新版本"] is False and v2["最新版本"] is True
    assert rec(r, "Q-2501-001")["最新版本"] is True


def test_6_version_tie_on_same_date_is_not_guessed():
    r = import_historical_quotes([edge()])
    a, b = rec(r, "E-008", version="A"), rec(r, "E-008", version="B")
    assert a["最新版本"] is None and b["最新版本"] is None
    assert any("無法判斷最新版本" in i.reason for i in r.issues)


def test_7_same_quote_number_different_lines_are_both_kept():
    r = import_historical_quotes([sales()])
    assert rec(r, "Q-2609-021", "1")["成品編號"] == "P-1002"
    assert rec(r, "Q-2609-021", "2")["成品編號"] == "P-1001"


# ---------- 8: leading zeros ----------

def test_8_leading_zeros_are_kept():
    r = import_historical_quotes([sales()])
    row = rec(r, "00123", "01")
    assert row["客戶代碼"] == "00125"


def test_8_numeric_ids_become_text_without_padding():
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "HistoricalQuotes"
    ws.append(HIST_REQUIRED)
    ws.append([123, 1, dt.datetime(2026, 1, 1), 45, 1001, 10, "pcs", "TWD", 100, "未稅"])
    buf = io.BytesIO()
    wb.save(buf)
    r = import_historical_quotes([HistoricalSource("n.xlsx", buf.getvalue(), "HistoricalQuotes")])
    row = r.records.iloc[0]
    assert (row["報價單號"], row["報價行號"], row["客戶代碼"], row["成品編號"]) == ("123", "1", "45", "1001")


# ---------- 9-13: invalid values and non-comparable rows ----------

def test_9_10_invalid_date_and_price_block_only_their_rows():
    r = import_historical_quotes([edge()])
    rows = {(i.row, i.column) for i in errors(r)}
    assert (3, "報價日期") in rows and (4, "報價單價") in rows
    assert (5, "客戶代碼") in rows and (12, "報價數量") in rows and (13, "計價單位") in rows
    assert set(r.records["報價單號"]) == {"E-001", "E-005", "E-006", "E-008"}


def test_conflicting_rows_with_same_key_are_all_blocked():
    r = import_historical_quotes([edge()])
    conflicts = [i for i in errors(r) if "衝突" in i.reason]
    assert {i.row for i in conflicts} == {8, 9}
    assert "E-007" not in set(r.records["報價單號"])


def test_11_missing_required_mapping_blocks_the_whole_file():
    m = _mapping("sales_dept")
    cols = {k: v for k, v in m["columns"].items() if k != "稅別"}
    r = import_historical_quotes([HistoricalSource(SALES.name, SALES.read_bytes(), m["source_sheet"], cols), legacy()])
    assert any(i.column == "稅別" and i.severity == ERROR for i in r.issues)
    assert set(r.records["來源檔案"]) == {LEGACY.name}  # the other file still imports


def test_11_missing_required_column_in_standard_file():
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "HistoricalQuotes"
    ws.append(HIST_REQUIRED[:-1])
    ws.append(["Q", "1", dt.datetime(2026, 1, 1), "C", "P", 1, "pcs", "TWD", 1])
    buf = io.BytesIO()
    wb.save(buf)
    r = import_historical_quotes([HistoricalSource("x.xlsx", buf.getvalue(), "HistoricalQuotes")])
    assert r.records.empty and any(i.column == "稅別" for i in errors(r))


def test_12_tax_unknown_or_included_is_not_comparable():
    r = import_historical_quotes([sales(), edge()])
    unknown = rec(r, "E-005")
    assert unknown["可直接比較"] is False and "稅別不明" in unknown["無法比較原因"]
    included = rec(r, "Q-2610-031")
    assert included["可直接比較"] is False and "含稅" in included["無法比較原因"]
    assert rec(r, "Q-2501-001")["可直接比較"] is True


def test_13_foreign_currency_is_not_comparable_and_not_converted():
    r = import_historical_quotes([sales()])
    usd = rec(r, "Q-2610-030")
    assert usd["可直接比較"] is False and "USD" in usd["無法比較原因"]
    assert usd["報價單價"] == 33 and usd["幣別"] == "USD"
    assert r.summary["可直接比較筆數"] == 8


def test_deal_status_blank_or_unknown_is_never_won():
    r = import_historical_quotes([sales(), edge()])
    assert rec(r, "Q-2603-007", version="1")["成交狀態"] == "未知"   # blank
    assert rec(r, "E-006")["成交狀態"] == "未知"                     # "大概有"
    assert any(i.row == 7 and "成交狀態" in i.reason for i in r.issues)
    assert set(r.records["成交狀態"]) <= {"成交", "未成交", "未知"}


def test_blank_values_never_become_nan_text():
    r = import_historical_quotes([sales(), legacy()])
    for col in HIST_OPTIONAL:
        if col in r.records:
            assert "nan" not in {str(v) for v in r.records[col] if isinstance(v, str)}
    assert rec(r, "Q-2612-002")["材質"] is None


# ---------- 14-15: limits and broken files ----------

def test_14_too_many_files(monkeypatch):
    monkeypatch.setattr(hq, "MAX_FILES", 1)
    r = import_historical_quotes([sales(), legacy()])
    assert r.records.empty and any("檔案數" in i.reason for i in errors(r))


def test_14_total_bytes_and_rows(monkeypatch):
    monkeypatch.setattr(hq, "MAX_TOTAL_BYTES", len(SALES.read_bytes()) + 10)
    r = import_historical_quotes([sales(), legacy()])
    assert r.records.empty and any("累計大小" in i.reason for i in errors(r))
    monkeypatch.setattr(hq, "MAX_TOTAL_BYTES", 10**9)
    monkeypatch.setattr(hq, "MAX_TOTAL_ROWS", 12)
    r = import_historical_quotes([sales(), legacy()])
    assert r.records.empty and any("累計資料列" in i.reason for i in errors(r))


def test_14_single_file_over_size_limit(monkeypatch):
    import core.reader as reader
    monkeypatch.setattr(reader, "MAX_FILE_BYTES", 1000)
    r = import_historical_quotes([sales()])
    assert r.records.empty and any("檔案過大" in i.reason for i in errors(r))


def test_15_corrupted_file_is_blocked_and_others_continue():
    bad = HistoricalSource("broken.xlsx", b"PK\x03\x04garbage", "HistoricalQuotes")
    r = import_historical_quotes([bad, legacy()])
    assert any(i.sheet.startswith("broken.xlsx") for i in errors(r))
    assert len(r.records) == 6


def test_15_formula_cells_are_not_executed():
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "HistoricalQuotes"
    ws.append(HIST_REQUIRED)
    ws.append(["Q", "1", dt.datetime(2026, 1, 1), "C", "P", 1, "pcs", "TWD", "=1000*2", "未稅"])
    buf = io.BytesIO()
    wb.save(buf)
    r = import_historical_quotes([HistoricalSource("f.xlsx", buf.getvalue(), "HistoricalQuotes")])
    assert r.records.empty and any(i.column == "報價單價" for i in errors(r))


def test_standardized_workbook_has_no_formulas_and_text_ids():
    r = import_historical_quotes([sales(), legacy(), edge()])
    df = r.records.copy()
    df.loc[df.index[0], "備註"] = '=HYPERLINK("http://example.invalid")'
    wb = openpyxl.load_workbook(io.BytesIO(build_historical_workbook(df)))
    ws = wb["HistoricalQuotes"]
    assert not [c for row in ws.iter_rows() for c in row if c.data_type == "f"]
    header = [c.value for c in ws[1]]
    assert ws.cell(2, header.index("報價單號") + 1).number_format == "@"
    assert "可直接比較" not in header  # computed columns are recomputed on import


def test_sample_mapping_files_load_with_the_existing_config_loader():
    from core.field_mapper import mapping_from_json
    for name in ("sales_dept", "legacy_system"):
        loaded = mapping_from_json((HIST / f"mapping_{name}.json").read_bytes())
        assert set(loaded) == {"HistoricalQuotes"}
