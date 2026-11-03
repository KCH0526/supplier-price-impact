"""Tests for core.reader: sheet / column checks and raw value normalisation."""

import io
import math
from pathlib import Path

import openpyxl

from core.reader import read_bom, read_price_increase
from core.validation import BOM_REQUIRED_COLUMNS, PRICE_REQUIRED_COLUMNS, has_blocking

ROOT = Path(__file__).resolve().parent.parent
SAMPLE_BOM = ROOT / "samples" / "sample_bom.xlsx"
SAMPLE_PRICE = ROOT / "samples" / "sample_price_increase.xlsx"
EDGE_BOM = ROOT / "tests" / "fixtures" / "test_bom_edge_cases.xlsx"
EDGE_PRICE = ROOT / "tests" / "fixtures" / "test_price_edge_cases.xlsx"


def make_workbook(sheet_name, header, rows, extra_sheet=None):
    """Build an in-memory .xlsx and return it as a BytesIO."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = sheet_name
    if header is not None:
        ws.append(header)
    for row in rows:
        ws.append(row)
    if extra_sheet:
        wb.create_sheet(extra_sheet)
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf


BOM_ROW = ["P-1", "成品", "M-1", "材料", "pcs", 2, 10]


# ---------- normal reads ----------

def test_read_sample_bom_from_path():
    result = read_bom(SAMPLE_BOM)
    assert result.issues == []
    df = result.data
    assert len(df) == 40
    assert df["成品編號"].nunique() == 6
    assert df["子件料號"].nunique() == 27
    for col in BOM_REQUIRED_COLUMNS:
        assert col in df.columns
    # Extension columns are kept and Excel row numbers start at 2.
    assert "工廠代碼" in df.columns
    assert df["excel_row"].iloc[0] == 2
    assert df["excel_row"].iloc[-1] == 41


def test_read_sample_price_from_path_and_str_path():
    result = read_price_increase(str(SAMPLE_PRICE))
    assert result.issues == []
    assert len(result.data) == 12
    for col in PRICE_REQUIRED_COLUMNS:
        assert col in result.data.columns
    assert "M-999" in set(result.data["子件料號"])


def test_read_from_binary_file_object_and_bytes():
    with open(SAMPLE_BOM, "rb") as fh:
        from_fh = read_bom(fh)
    from_bytes = read_bom(SAMPLE_BOM.read_bytes())
    assert len(from_fh.data) == 40
    assert len(from_bytes.data) == 40
    assert from_fh.issues == [] and from_bytes.issues == []


def test_edge_case_fixtures_are_readable():
    bom = read_bom(EDGE_BOM)
    price = read_price_increase(EDGE_PRICE)
    assert bom.issues == [] and len(bom.data) == 14
    assert price.issues == [] and len(price.data) == 17


# ---------- sheet / column checks ----------

def test_missing_sheet_is_blocking():
    buf = make_workbook("Sheet1", BOM_REQUIRED_COLUMNS, [BOM_ROW])
    result = read_bom(buf)
    assert result.data is None
    assert has_blocking(result.issues)
    issue = result.issues[0]
    assert issue.sheet == "BOM"
    assert "缺少工作表" in issue.reason


def test_bom_sheet_missing_from_price_file():
    result = read_bom(SAMPLE_PRICE)
    assert result.data is None
    assert has_blocking(result.issues)


def test_missing_required_columns_reported_individually():
    header = [c for c in BOM_REQUIRED_COLUMNS if c not in ("用量", "原單價")]
    buf = make_workbook("BOM", header, [["P-1", "成品", "M-1", "材料", "pcs"]])
    result = read_bom(buf)
    assert result.data is None
    missing = {i.column for i in result.issues if i.severity == "error"}
    assert missing == {"用量", "原單價"}
    assert all(i.row == 1 for i in result.issues)


def test_columns_are_matched_by_header_name_not_position():
    header = list(reversed(BOM_REQUIRED_COLUMNS))
    buf = make_workbook("BOM", header, [list(reversed(BOM_ROW))])
    result = read_bom(buf)
    assert result.issues == []
    row = result.data.iloc[0]
    assert row["子件料號"] == "M-1"
    assert row["用量"] == 2


def test_empty_sheet_and_header_only_sheet_are_blocking():
    empty = read_bom(make_workbook("BOM", None, []))
    assert empty.data is None and has_blocking(empty.issues)
    header_only = read_bom(make_workbook("BOM", BOM_REQUIRED_COLUMNS, []))
    assert header_only.data is None and has_blocking(header_only.issues)
    assert "沒有資料列" in header_only.issues[0].reason


def test_unreadable_file_is_blocking():
    result = read_bom(io.BytesIO(b"not an excel file"))
    assert result.data is None
    assert has_blocking(result.issues)


# ---------- value normalisation ----------

def test_leading_zeros_in_text_ids_are_kept():
    buf = make_workbook(
        "BOM",
        BOM_REQUIRED_COLUMNS,
        [["0012", "成品", "000345", "材料", "pcs", 1, 5]],
    )
    row = read_bom(buf).data.iloc[0]
    assert row["成品編號"] == "0012"
    assert row["子件料號"] == "000345"


def test_empty_cells_become_none_not_nan():
    buf = make_workbook(
        "BOM",
        BOM_REQUIRED_COLUMNS + ["備註"],
        [["P-1", None, "M-1", "  ", "pcs", None, 10, None]],
    )
    row = read_bom(buf).data.iloc[0]
    for col in ("成品名稱", "子件名稱", "用量", "備註"):
        assert row[col] is None
        assert str(row[col]) != "nan"


def test_blank_rows_are_skipped_but_row_numbers_stay_correct():
    buf = make_workbook(
        "BOM",
        BOM_REQUIRED_COLUMNS,
        [BOM_ROW, [None] * 7, ["P-2", "成品2", "M-2", "材料2", "kg", 1, 3]],
    )
    df = read_bom(buf).data
    assert list(df["excel_row"]) == [2, 4]


def test_edge_price_blank_price_is_none():
    df = read_price_increase(EDGE_PRICE).data
    m203 = df[df["子件料號"] == "M-203"].iloc[0]
    assert m203["新單價"] is None
    assert not (isinstance(m203["新單價"], float) and math.isnan(m203["新單價"]))


def test_numeric_id_cells_are_converted_to_text():
    buf = make_workbook("BOM", BOM_REQUIRED_COLUMNS, [[1001, "成品", 345.0, "材料", "pcs", 1, 5]])
    row = read_bom(buf).data.iloc[0]
    assert row["成品編號"] == "1001"
    assert row["子件料號"] == "345"


def test_duplicate_required_header_is_blocking():
    header = BOM_REQUIRED_COLUMNS + ["子件料號"]
    buf = make_workbook("BOM", header, [BOM_ROW + ["M-1"]])
    result = read_bom(buf)
    assert result.data is None
    assert any("重複" in i.reason and i.column == "子件料號" for i in result.issues)
