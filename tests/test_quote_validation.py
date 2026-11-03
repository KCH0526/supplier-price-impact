"""Tests for core.quote_validation: row-level checks of OpenQuotes."""

import datetime as dt

import pandas as pd
import pytest

from core.quote_reader import QUOTE_REQUIRED_COLUMNS, read_open_quotes
from core.quote_validation import (
    QUOTE_ACTIVE,
    QUOTE_INACTIVE,
    QUOTE_UNKNOWN,
    classify_quote_status,
    validate_open_quotes,
)
from core.validation import ERROR, WARNING
from tests.test_quote_reader import EDGE_QUOTES, SAMPLE_QUOTES

D1, D2 = dt.datetime(2026, 11, 1), dt.datetime(2027, 1, 31)


def frame(rows):
    df = pd.DataFrame([list(r) for r in rows], columns=QUOTE_REQUIRED_COLUMNS, dtype=object)
    df.insert(0, "excel_row", range(2, 2 + len(df)))
    return df


def row(**changes):
    base = dict(zip(QUOTE_REQUIRED_COLUMNS,
                    ["SQ-1", "1", "P-1001", "C-001", 1000, "TWD", 50, D1, D2, "有效"]))
    base.update(changes)
    return [base[c] for c in QUOTE_REQUIRED_COLUMNS]


def errors(issues):
    return [(i.row, i.column) for i in issues if i.severity == ERROR]


def warnings(issues):
    return [(i.row, i.column) for i in issues if i.severity == WARNING]


def test_valid_row_has_no_issues():
    assert validate_open_quotes(frame([row()])) == []


def test_sample_only_reports_the_cancelled_quote_as_warning():
    issues = validate_open_quotes(read_open_quotes(SAMPLE_QUOTES).data)
    assert errors(issues) == []
    assert warnings(issues) == [(9, "報價狀態")]
    assert issues[0].sheet == "OpenQuotes"


@pytest.mark.parametrize("column", ["報價單號", "行號", "成品編號", "客戶代碼"])
def test_blank_identifiers_block(column):
    assert errors(validate_open_quotes(frame([row(**{column: None})]))) == [(2, column)]


@pytest.mark.parametrize("price", [None, 0, -1, "待議", "nan", "inf"])
def test_invalid_price_blocks(price):
    assert errors(validate_open_quotes(frame([row(未稅報價單價=price)]))) == [(2, "未稅報價單價")]


@pytest.mark.parametrize("qty", [None, 0, -5, "很多", 2.5])
def test_invalid_quantity_blocks(qty):
    # Blank is never treated as 0; products are priced per piece, so a
    # fractional quantity has no defined business meaning in the MVP.
    assert errors(validate_open_quotes(frame([row(報價數量=qty)]))) == [(2, "報價數量")]


def test_integral_float_quantity_is_accepted():
    assert validate_open_quotes(frame([row(報價數量=50.0)])) == []


@pytest.mark.parametrize("currency", [None, "USD", "twd "])
def test_non_twd_currency_blocks(currency):
    # Only the exact code TWD is accepted; no exchange rate is looked up or guessed.
    assert errors(validate_open_quotes(frame([row(報價幣別=currency)]))) == [(2, "報價幣別")]


@pytest.mark.parametrize("column", ["生效日", "截止日"])
@pytest.mark.parametrize("value", [None, "下個月", "2026-12-01錯誤", 46000])
def test_invalid_dates_block(column, value):
    assert errors(validate_open_quotes(frame([row(**{column: value})]))) == [(2, column)]


def test_start_after_end_blocks_and_same_day_is_valid():
    assert errors(validate_open_quotes(frame([row(生效日=D2, 截止日=D1)]))) == [(2, "截止日")]
    assert validate_open_quotes(frame([row(生效日=D1, 截止日=D1)])) == []


def test_status_classification():
    assert classify_quote_status("有效") == QUOTE_ACTIVE
    for value in ("已取消", "取消", "失效", "已失效", "作廢", "已作廢"):
        assert classify_quote_status(value) == QUOTE_INACTIVE
    for value in (None, "", "處理中", "有效?", "valid"):
        assert classify_quote_status(value) == QUOTE_UNKNOWN


def test_cancelled_status_is_warning_and_unknown_status_blocks():
    issues = validate_open_quotes(frame([row(報價狀態="已取消"), row(行號="2", 報價狀態=None),
                                         row(行號="3", 報價狀態="處理中")]))
    assert warnings(issues) == [(2, "報價狀態")]
    assert errors(issues) == [(3, "報價狀態"), (4, "報價狀態")]


def test_duplicate_quote_no_and_line_blocks_every_occurrence():
    issues = validate_open_quotes(frame([row(), row(成品編號="P-1002"), row(行號="2")]))
    assert errors(issues) == [(2, "行號"), (3, "行號")]


def test_same_product_on_different_quotes_is_not_duplicate():
    rows = [row(), row(報價單號="SQ-2", 客戶代碼="C-002"), row(行號="2")]
    assert validate_open_quotes(frame(rows)) == []


def test_edge_fixture_reports_expected_rows():
    issues = validate_open_quotes(read_open_quotes(EDGE_QUOTES).data)
    found = set(errors(issues))
    expected = {
        (3, "行號"), (4, "行號"),          # duplicate 報價單號 + 行號
        (6, "未稅報價單價"),               # blank price
        (7, "未稅報價單價"),               # zero price
        (8, "報價數量"),                   # negative quantity
        (9, "報價幣別"),                   # USD
        (16, "報價狀態"),                  # blank status
    }
    assert expected <= found
    assert (5, "報價狀態") in set(warnings(issues))   # cancelled
