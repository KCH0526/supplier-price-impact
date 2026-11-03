"""Tests for core.quote_reader: the OpenQuotes (customer quote) workbook."""

import datetime as dt
import io
from pathlib import Path

import openpyxl

from core.quote_reader import QUOTE_REQUIRED_COLUMNS, QUOTE_SHEET, read_open_quotes
from core.validation import has_blocking

ROOT = Path(__file__).resolve().parents[1]
SAMPLE_QUOTES = ROOT / "samples" / "sample_open_quotes.xlsx"
EDGE_QUOTES = ROOT / "tests" / "fixtures" / "test_open_quotes_edge_cases.xlsx"

D1, D2 = dt.datetime(2026, 11, 1), dt.datetime(2027, 1, 31)
ROW = ["SQ-1", "1", "P-1001", "C-001", 1000, "TWD", 50, D1, D2, "有效"]


def make(header, rows, sheet=QUOTE_SHEET):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = sheet
    ws.append(header)
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_required_columns_are_exactly_the_spec():
    assert QUOTE_SHEET == "OpenQuotes"
    assert QUOTE_REQUIRED_COLUMNS == [
        "報價單號", "行號", "成品編號", "客戶代碼", "未稅報價單價",
        "報價幣別", "報價數量", "生效日", "截止日", "報價狀態",
    ]


def test_read_sample_from_path_bytes_and_file_object():
    from_path = read_open_quotes(SAMPLE_QUOTES)
    assert from_path.issues == []
    assert len(from_path.data) == 8
    assert read_open_quotes(SAMPLE_QUOTES.read_bytes()).data.shape == from_path.data.shape
    with open(SAMPLE_QUOTES, "rb") as fh:
        assert len(read_open_quotes(fh).data) == 8
    first = from_path.data.iloc[0]
    assert first["excel_row"] == 2
    assert first["報價單號"] == "SQ-2611-001"
    assert first["行號"] == "1"


def test_sample_contains_acceptance_cases_a_and_b():
    df = read_open_quotes(SAMPLE_QUOTES).data
    a = df[(df["成品編號"] == "P-1001") & (df["客戶代碼"] == "C-001")].iloc[0]
    assert (a["未稅報價單價"], a["報價數量"]) == (1000, 50)
    b = df[(df["成品編號"] == "P-1002") & (df["客戶代碼"] == "C-002")].iloc[0]
    assert (b["未稅報價單價"], b["報價數量"]) == (450, 10)


def test_edge_fixture_is_readable():
    result = read_open_quotes(EDGE_QUOTES)
    assert result.issues == []
    assert len(result.data) >= 15


def test_missing_sheet_and_missing_columns_block():
    wrong_sheet = read_open_quotes(make(QUOTE_REQUIRED_COLUMNS, [ROW], sheet="Quotes"))
    assert wrong_sheet.data is None and has_blocking(wrong_sheet.issues)
    assert "缺少工作表" in wrong_sheet.issues[0].reason

    header = [c for c in QUOTE_REQUIRED_COLUMNS if c not in ("行號", "報價狀態")]
    row = [v for c, v in zip(QUOTE_REQUIRED_COLUMNS, ROW) if c in header]
    missing = read_open_quotes(make(header, [row]))
    assert missing.data is None
    assert {i.column for i in missing.issues} == {"行號", "報價狀態"}


def test_ids_are_text_and_keep_leading_zeros():
    rows = [["00123", "001", "0042", "00125", 10, "TWD", 1, D1, D2, "有效"],
            [4567, 2, 1001, 89, 10, "TWD", 1, D1, D2, "有效"],
            ["SQ-9", 3.0, "P-1", "C-1", 10, "TWD", 1, D1, D2, "有效"]]
    df = read_open_quotes(make(QUOTE_REQUIRED_COLUMNS, rows)).data
    assert list(df.iloc[0][["報價單號", "行號", "成品編號", "客戶代碼"]]) == ["00123", "001", "0042", "00125"]
    assert list(df.iloc[1][["報價單號", "行號", "成品編號", "客戶代碼"]]) == ["4567", "2", "1001", "89"]
    assert df.iloc[2]["行號"] == "3"


def test_empty_cells_are_none_not_nan():
    row = ["SQ-1", None, "P-1", "  ", None, "TWD", None, D1, D2, None]
    rec = read_open_quotes(make(QUOTE_REQUIRED_COLUMNS, [row])).data.iloc[0]
    for col in ("行號", "客戶代碼", "未稅報價單價", "報價數量", "報價狀態"):
        assert rec[col] is None
        assert str(rec[col]) != "nan"
