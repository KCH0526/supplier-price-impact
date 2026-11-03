"""Tests for core.validation: row-level checks of identifiers, numbers and dates."""

import datetime as dt
from decimal import Decimal

import pandas as pd
import pytest

from core.reader import read_bom, read_price_increase
from core.validation import (
    BOM_REQUIRED_COLUMNS,
    PRICE_REQUIRED_COLUMNS,
    ERROR,
    WARNING,
    has_blocking,
    parse_date,
    parse_number,
    validate_bom,
    validate_price_increase,
)
from tests.test_reader import EDGE_BOM, EDGE_PRICE, SAMPLE_BOM, SAMPLE_PRICE

D = dt.datetime(2026, 12, 1)


def bom_frame(rows, extra_columns=()):
    columns = list(BOM_REQUIRED_COLUMNS) + list(extra_columns)
    df = pd.DataFrame(rows, columns=columns, dtype=object)
    df.insert(0, "excel_row", range(2, 2 + len(df)))
    return df


def price_frame(rows, extra_columns=()):
    columns = list(PRICE_REQUIRED_COLUMNS) + list(extra_columns)
    df = pd.DataFrame(rows, columns=columns, dtype=object)
    df.insert(0, "excel_row", range(2, 2 + len(df)))
    return df


def errors(issues):
    return [i for i in issues if i.severity == ERROR]


def warnings(issues):
    return [i for i in issues if i.severity == WARNING]


# ---------- parse helpers ----------

@pytest.mark.parametrize(
    "value, expected",
    [(2, Decimal("2")), (0.45, Decimal("0.45")), ("3.10", Decimal("3.10")), (" 7 ", Decimal("7"))],
)
def test_parse_number_valid(value, expected):
    assert parse_number(value) == expected


@pytest.mark.parametrize("value", [None, "", "待確認", "nan", "inf", float("nan"), True, D])
def test_parse_number_invalid(value):
    assert parse_number(value) is None


def test_parse_date():
    assert parse_date(D) == dt.date(2026, 12, 1)
    assert parse_date(dt.date(2026, 12, 1)) == dt.date(2026, 12, 1)
    assert parse_date("2026-12-01") == dt.date(2026, 12, 1)
    assert parse_date(" 2026-12-01 ") == dt.date(2026, 12, 1)
    for bad in (None, "", "下個月", "2026-13-01", 46000):
        assert parse_date(bad) is None


@pytest.mark.parametrize(
    "bad",
    ["2026-12-01錯誤", "2026-12-01 abc", "2026-12-01T00:00", "2026-12-1", "20261201", "2026/12/01"],
)
def test_parse_date_rejects_text_beyond_yyyy_mm_dd(bad):
    assert parse_date(bad) is None


def test_price_date_with_trailing_garbage_is_blocking():
    df = price_frame([["M-1", "材料", "pcs", "TWD", 12, "2026-12-01錯誤"]])
    assert [(i.row, i.column) for i in errors(validate_price_increase(df))] == [(2, "生效日")]


# ---------- sample and fixture files ----------

def test_sample_files_have_no_issues():
    assert validate_bom(read_bom(SAMPLE_BOM).data) == []
    assert validate_price_increase(read_price_increase(SAMPLE_PRICE).data) == []


def test_sample_bom_shared_components_are_not_duplicates():
    # M-102 is used by P-1001, P-1004 and P-1005: legal, no issue.
    df = read_bom(SAMPLE_BOM).data
    assert (df["子件料號"] == "M-102").sum() == 3
    assert validate_bom(df) == []


def test_edge_bom_fixture_has_valid_basic_types():
    # Business rules (未核准、基準產量≠1、半成品) belong to a later PR.
    assert errors(validate_bom(read_bom(EDGE_BOM).data)) == []


def test_edge_price_fixture_invalid_prices_reported_with_row_and_column():
    issues = validate_price_increase(read_price_increase(EDGE_PRICE).data)
    found = {(i.row, i.column) for i in errors(issues)}
    # M-203 blank (row 5), M-204 zero (row 6), M-205 text '待確認' (row 7)
    assert found == {(5, "新單價"), (6, "新單價"), (7, "新單價")}
    for issue in errors(issues):
        assert issue.sheet == "PriceIncrease"
        assert issue.reason


def test_edge_price_legal_price_decrease_is_not_an_error():
    issues = validate_price_increase(read_price_increase(EDGE_PRICE).data)
    # M-209 (20 -> 17) is on row 11 and must not be flagged.
    assert not [i for i in issues if i.row == 11]


# ---------- BOM rules ----------

def test_bom_empty_identifiers_are_blocking():
    df = bom_frame([[None, "成品", "M-1", "材料", "pcs", 1, 5], ["P-1", "成品", None, "材料", "pcs", 1, 5]])
    issues = validate_bom(df)
    assert {(i.row, i.column) for i in errors(issues)} == {(2, "成品編號"), (3, "子件料號")}
    assert has_blocking(issues)


def test_bom_empty_unit_is_blocking_and_empty_name_is_warning():
    df = bom_frame([["P-1", None, "M-1", None, None, 1, 5]])
    issues = validate_bom(df)
    assert {i.column for i in errors(issues)} == {"單位"}
    assert {i.column for i in warnings(issues)} == {"成品名稱", "子件名稱"}


@pytest.mark.parametrize("qty", [None, 0, -1, "兩個", float("nan")])
def test_bom_invalid_quantity_is_blocking(qty):
    issues = validate_bom(bom_frame([["P-1", "成品", "M-1", "材料", "pcs", qty, 5]]))
    assert [(i.row, i.column) for i in errors(issues)] == [(2, "用量")]


@pytest.mark.parametrize("price", [None, -0.5, "待確認"])
def test_bom_invalid_original_price_is_blocking(price):
    issues = validate_bom(bom_frame([["P-1", "成品", "M-1", "材料", "pcs", 1, price]]))
    assert [(i.row, i.column) for i in errors(issues)] == [(2, "原單價")]


def test_bom_zero_original_price_is_allowed():
    assert validate_bom(bom_frame([["P-1", "成品", "M-1", "材料", "pcs", 1, 0]])) == []


def test_bom_invalid_optional_dates_and_numbers():
    df = bom_frame(
        [["P-1", "成品", "M-1", "材料", "pcs", 1, 5, "不明", D, 0]],
        extra_columns=["生效起日", "生效迄日", "BOM基準產量"],
    )
    issues = validate_bom(df)
    assert {i.column for i in errors(issues)} == {"生效起日", "BOM基準產量"}


def test_bom_optional_columns_may_be_empty():
    df = bom_frame(
        [["P-1", "成品", "M-1", "材料", "pcs", 1, 5, None, None]],
        extra_columns=["生效起日", "BOM基準產量"],
    )
    assert validate_bom(df) == []


def test_bom_same_component_on_different_lines_is_not_an_error():
    df = bom_frame(
        [
            ["P-1", "成品", "M-1", "材料", "pcs", 1, 5, 10],
            ["P-1", "成品", "M-1", "材料", "pcs", 2, 5, 20],
        ],
        extra_columns=["行號"],
    )
    assert validate_bom(df) == []


def test_bom_repeated_line_is_only_a_warning():
    row = ["P-1", "成品", "M-1", "材料", "pcs", 1, 5, 10]
    issues = validate_bom(bom_frame([row, list(row)], extra_columns=["行號"]))
    assert errors(issues) == []
    assert [i.row for i in warnings(issues)] == [3]


def test_bom_repeated_component_without_line_numbers_is_only_a_warning():
    row = ["P-1", "成品", "M-1", "材料", "pcs", 1, 5]
    issues = validate_bom(bom_frame([row, list(row)]))
    assert errors(issues) == []
    assert len(warnings(issues)) == 1


# ---------- PriceIncrease rules ----------

PRICE_ROW = ["M-1", "材料", "pcs", "TWD", 12, D]


def test_price_empty_identifier_unit_currency_are_blocking():
    df = price_frame([[None, "材料", None, None, 12, D]])
    assert {i.column for i in errors(validate_price_increase(df))} == {"子件料號", "單位", "幣別"}


@pytest.mark.parametrize("price", [None, 0, -3, "待確認", "nan"])
def test_price_invalid_new_price_is_blocking(price):
    df = price_frame([["M-1", "材料", "pcs", "TWD", price, D]])
    assert [(i.row, i.column) for i in errors(validate_price_increase(df))] == [(2, "新單價")]


@pytest.mark.parametrize("value", [None, "下個月", 46000])
def test_price_invalid_effective_date_is_blocking(value):
    df = price_frame([["M-1", "材料", "pcs", "TWD", 12, value]])
    assert [(i.row, i.column) for i in errors(validate_price_increase(df))] == [(2, "生效日")]


def test_price_text_date_in_iso_format_is_accepted():
    df = price_frame([["M-1", "材料", "pcs", "TWD", 12, "2026-12-01"]])
    assert validate_price_increase(df) == []


def test_price_optional_end_date_and_price_qty():
    df = price_frame([PRICE_ROW + ["錯誤日期", -1]], extra_columns=["價格迄日", "計價數量"])
    assert {i.column for i in errors(validate_price_increase(df))} == {"價格迄日", "計價數量"}


def test_issue_to_dict_contains_location_and_reason():
    df = price_frame([["M-1", "材料", "pcs", "TWD", 0, D]])
    d = validate_price_increase(df)[0].to_dict()
    assert d["工作表"] == "PriceIncrease"
    assert d["Excel列號"] == 2
    assert d["欄位"] == "新單價"
    assert d["嚴重度"] == "阻擋"
    assert d["原因"]
