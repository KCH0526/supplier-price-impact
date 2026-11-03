"""Tests for core.matcher: quote selection, business exceptions, product status."""

import datetime as dt
from decimal import Decimal

import openpyxl
import pandas as pd
import pytest

from core.matcher import (
    INCOMPLETE,
    COMPLETE,
    STATUS_ADJUSTED,
    STATUS_UNCHANGED,
    match_prices,
)
from core.reader import read_bom, read_price_increase
from tests.test_reader import EDGE_BOM, EDGE_PRICE, ROOT, SAMPLE_BOM, SAMPLE_PRICE

AS_OF = dt.date(2026, 12, 1)
REFERENCE = ROOT / "tests" / "fixtures" / "expected_result_reference.xlsx"


def run(bom_path, price_path, as_of=AS_OF):
    return match_prices(read_bom(bom_path).data, read_price_increase(price_path).data, as_of)


@pytest.fixture(scope="module")
def sample():
    return run(SAMPLE_BOM, SAMPLE_PRICE)


@pytest.fixture(scope="module")
def edge():
    return run(EDGE_BOM, EDGE_PRICE)


def exc_by_item(result):
    """{子件料號: {(類型, 工作表, Excel列號, 是否阻擋), ...}}"""
    out = {}
    for rec in result.exceptions.to_dict("records"):
        out.setdefault(rec["子件料號"], set()).add(
            (rec["類型"], rec["工作表"], rec["Excel列號"], rec["是否阻擋"])
        )
    return out


# ---------- normal sample ----------

def test_sample_all_lines_matched_and_products_complete(sample):
    assert len(sample.matched_items) == 40
    adjusted = sample.matched_items[sample.matched_items["配對狀態"] == STATUS_ADJUSTED]
    # 11 quoted items; shared items (M-102, M-112, M-115, M-123) give 16 BOM lines.
    assert adjusted["子件料號"].nunique() == 11
    assert len(adjusted) == 16
    status = dict(zip(sample.product_status["成品編號"], sample.product_status["狀態"]))
    assert status == {f"P-100{i}": COMPLETE for i in range(1, 7)}


def test_sample_only_exception_is_unmatched_m999(sample):
    assert exc_by_item(sample) == {
        "M-999": {("漲價料號未匹配", "PriceIncrease", 13, False)},
    }
    rec = sample.exceptions.iloc[0]
    assert rec["影響成品"] == ""


def test_sample_matches_reference_line_audit(sample):
    wb = openpyxl.load_workbook(REFERENCE, read_only=True)
    rows = list(wb["Line Audit"].iter_rows(min_row=2, values_only=True))
    wb.close()
    expected = {(r[0], r[2]): (Decimal(str(r[7])), r[11]) for r in rows}
    got = {
        (r["成品編號"], r["子件料號"]): (r["適用單價"], r["配對狀態"])
        for r in sample.matched_items.to_dict("records")
    }
    assert got == expected


def test_shared_component_is_not_a_duplicate(sample):
    m102 = sample.matched_items[sample.matched_items["子件料號"] == "M-102"]
    assert sorted(m102["成品編號"]) == ["P-1001", "P-1004", "P-1005"]
    assert set(m102["適用單價"]) == {Decimal("3.1")}
    assert set(m102["報價列號"]) == {3}


def test_matched_items_keep_audit_columns(sample):
    row = sample.matched_items[
        (sample.matched_items["成品編號"] == "P-1001") & (sample.matched_items["子件料號"] == "M-101")
    ].iloc[0]
    assert row["BOM列號"] == 2
    assert row["報價列號"] == 2
    assert row["供應商代碼"] == "V-001"
    assert row["單位"] == "pcs"
    assert row["原單價"] == Decimal("180")
    assert row["適用單價"] == Decimal("196")
    assert row["單價差額"] == Decimal("16")
    assert row["報價單號"] == "Q-2612-001"

    unchanged = sample.matched_items[sample.matched_items["子件料號"] == "M-103"].iloc[0]
    assert unchanged["配對狀態"] == STATUS_UNCHANGED
    assert unchanged["適用單價"] == unchanged["原單價"]
    assert unchanged["報價列號"] is None


def test_as_of_date_is_required():
    with pytest.raises(TypeError):
        match_prices(read_bom(SAMPLE_BOM).data, read_price_increase(SAMPLE_PRICE).data)


def test_before_effective_date_nothing_is_adjusted():
    result = run(SAMPLE_BOM, SAMPLE_PRICE, as_of=dt.date(2026, 11, 30))
    assert (result.matched_items["配對狀態"] == STATUS_UNCHANGED).all()
    assert set(result.product_status["狀態"]) == {COMPLETE}


# ---------- edge-case fixtures ----------

EDGE_EXPECTED = {
    "M-201": {("重複報價", "PriceIncrease", 2, True), ("重複報價", "PriceIncrease", 3, True)},
    "M-202": {("單位不一致", "PriceIncrease", 4, True)},
    "M-203": {("報價資料無效", "PriceIncrease", 5, True)},
    "M-204": {("報價資料無效", "PriceIncrease", 6, True)},
    "M-205": {("報價資料無效", "PriceIncrease", 7, True)},
    "M-206": {("幣別不一致", "PriceIncrease", 8, True)},
    "M-207": {("計價數量不支援", "PriceIncrease", 9, True)},
    "M-208": {("報價尚未生效", "PriceIncrease", 10, False)},
    "M-210": {("供應商不符", "PriceIncrease", 12, True)},
    "M-211": {("一料多供應商", "PriceIncrease", 13, True), ("一料多供應商", "PriceIncrease", 14, True)},
    "M-213": {("BOM 未核准", "BOM", 14, True), ("BOM 基準產量不支援", "BOM", 14, True)},
    "M-214": {("未展開半成品", "BOM", 15, True)},
    "M-999": {("漲價料號未匹配", "PriceIncrease", 18, False)},
}


def test_edge_exceptions_exact(edge):
    assert exc_by_item(edge) == EDGE_EXPECTED


@pytest.mark.parametrize("item", sorted(EDGE_EXPECTED))
def test_edge_exception_per_item(edge, item):
    assert exc_by_item(edge)[item] == EDGE_EXPECTED[item]


def test_edge_exceptions_have_reason_and_affected_product(edge):
    for rec in edge.exceptions.to_dict("records"):
        assert rec["原因"]
        if rec["是否阻擋"]:
            assert rec["影響成品"] in {"P-X01", "P-X02"}


def test_edge_matched_items_only_safe_lines(edge):
    got = {r["子件料號"]: (r["配對狀態"], r["適用單價"]) for r in edge.matched_items.to_dict("records")}
    assert got == {
        "M-208": (STATUS_UNCHANGED, Decimal("15")),  # not yet effective: keep original price
        "M-209": (STATUS_ADJUSTED, Decimal("17")),  # legal decrease
        "M-212": (STATUS_ADJUSTED, Decimal("28")),
    }
    m209 = edge.matched_items[edge.matched_items["子件料號"] == "M-209"].iloc[0]
    assert m209["單價差額"] == Decimal("-3")


def test_edge_invalid_quotes_are_not_treated_as_unchanged(edge):
    blocked = {"M-203", "M-204", "M-205"}
    assert not blocked & set(edge.matched_items["子件料號"])


def test_edge_products_incomplete(edge):
    status = edge.product_status.set_index("成品編號")
    assert status.loc["P-X01", "狀態"] == INCOMPLETE
    assert status.loc["P-X02", "狀態"] == INCOMPLETE
    assert status.loc["P-X02", "阻擋料號"] == "M-213, M-214"
    assert status.loc["P-X01", "BOM行數"] == 12
    assert status.loc["P-X01", "可計算行數"] == 3


def test_matched_items_flag_incomplete_products(edge, sample):
    assert not edge.matched_items["成品試算完整"].any()
    assert sample.matched_items["成品試算完整"].all()


# ---------- small synthetic cases ----------

D = dt.datetime(2026, 12, 1)
BOM_COLS = ["成品編號", "成品名稱", "子件料號", "子件名稱", "單位", "用量", "原單價", "供應商代碼"]
PRICE_COLS = ["子件料號", "子件名稱", "單位", "幣別", "新單價", "生效日", "供應商代碼"]


def frame(columns, rows, extra=()):
    df = pd.DataFrame([list(r) for r in rows], columns=list(columns) + list(extra), dtype=object)
    df.insert(0, "excel_row", range(2, 2 + len(df)))
    return df


def test_one_blocked_product_does_not_block_others():
    bom = frame(BOM_COLS, [
        ["P-A", "A", "M-1", "x", "pcs", 1, 10, "V-1"],
        ["P-B", "B", "M-2", "y", "pcs", 1, 10, "V-1"],
    ])
    price = frame(PRICE_COLS, [
        ["M-1", "x", "kg", "TWD", 12, D, "V-1"],  # unit mismatch -> blocks P-A only
        ["M-2", "y", "pcs", "TWD", 11, D, "V-1"],
    ])
    result = match_prices(bom, price, AS_OF)
    status = dict(zip(result.product_status["成品編號"], result.product_status["狀態"]))
    assert status == {"P-A": INCOMPLETE, "P-B": COMPLETE}
    assert list(result.matched_items["子件料號"]) == ["M-2"]


def test_blocked_item_shared_by_two_products_blocks_both():
    bom = frame(BOM_COLS, [
        ["P-A", "A", "M-1", "x", "pcs", 1, 10, "V-1"],
        ["P-B", "B", "M-1", "x", "pcs", 2, 10, "V-1"],
    ])
    price = frame(PRICE_COLS, [["M-1", "x", "pcs", "USD", 1, D, "V-1"]])
    result = match_prices(bom, price, AS_OF)
    assert set(result.product_status["狀態"]) == {INCOMPLETE}
    assert len(result.exceptions) == 1
    assert result.exceptions.iloc[0]["影響成品"] == "P-A, P-B"


def test_expired_quote_keeps_original_price_with_warning():
    bom = frame(BOM_COLS, [["P-A", "A", "M-1", "x", "pcs", 1, 10, "V-1"]])
    price = frame(PRICE_COLS, [["M-1", "x", "pcs", "TWD", 12, dt.datetime(2026, 1, 1), "V-1",
                                dt.datetime(2026, 6, 30)]], extra=["價格迄日"])
    result = match_prices(bom, price, AS_OF)
    assert result.matched_items.iloc[0]["配對狀態"] == STATUS_UNCHANGED
    assert result.matched_items.iloc[0]["適用單價"] == Decimal("10")
    assert list(result.exceptions["類型"]) == ["報價已過期"]
    assert not result.exceptions.iloc[0]["是否阻擋"]
    assert result.product_status.iloc[0]["狀態"] == COMPLETE


def test_end_date_on_as_of_date_is_still_valid():
    bom = frame(BOM_COLS, [["P-A", "A", "M-1", "x", "pcs", 1, 10, "V-1"]])
    price = frame(PRICE_COLS, [["M-1", "x", "pcs", "TWD", 12, D, "V-1", D]], extra=["價格迄日"])
    result = match_prices(bom, price, AS_OF)
    assert result.matched_items.iloc[0]["配對狀態"] == STATUS_ADJUSTED


@pytest.mark.parametrize("status", ["待核准", None])
def test_unapproved_quote_blocks(status):
    bom = frame(BOM_COLS, [["P-A", "A", "M-1", "x", "pcs", 1, 10, "V-1"]])
    price = frame(PRICE_COLS, [["M-1", "x", "pcs", "TWD", 12, D, "V-1", status]], extra=["報價狀態"])
    result = match_prices(bom, price, AS_OF)
    assert list(result.exceptions["類型"]) == ["報價未核准"]
    assert result.product_status.iloc[0]["狀態"] == INCOMPLETE
    assert result.matched_items.empty


def test_plant_mismatch_blocks():
    bom = frame(BOM_COLS, [["P-A", "A", "M-1", "x", "pcs", 1, 10, "V-1", "TW01"]], extra=["工廠代碼"])
    price = frame(PRICE_COLS, [["M-1", "x", "pcs", "TWD", 12, D, "V-1", "TW02"]], extra=["工廠代碼"])
    result = match_prices(bom, price, AS_OF)
    assert list(result.exceptions["類型"]) == ["工廠不符"]
    assert result.product_status.iloc[0]["狀態"] == INCOMPLETE


def test_invalid_bom_line_blocks_its_product():
    bom = frame(BOM_COLS, [
        ["P-A", "A", "M-1", "x", "pcs", "兩個", 10, "V-1"],
        ["P-B", "B", "M-2", "y", "pcs", 1, 10, "V-1"],
    ])
    price = frame(PRICE_COLS, [["M-9", "z", "pcs", "TWD", 1, D, "V-1"]])
    result = match_prices(bom, price, AS_OF)
    types = dict(zip(result.exceptions["類型"], result.exceptions["Excel列號"]))
    assert types == {"BOM 資料無效": 2, "漲價料號未匹配": 2}
    status = dict(zip(result.product_status["成品編號"], result.product_status["狀態"]))
    assert status == {"P-A": INCOMPLETE, "P-B": COMPLETE}


def test_bom_currency_and_price_qty_not_supported():
    bom = frame(
        BOM_COLS,
        [["P-A", "A", "M-1", "x", "pcs", 1, 10, "V-1", "USD", 1],
         ["P-B", "B", "M-2", "y", "pcs", 1, 10, "V-1", "TWD", 100]],
        extra=["原單價幣別", "原單價計價數量"],
    )
    price = frame(PRICE_COLS, [["M-9", "z", "pcs", "TWD", 1, D, "V-1"]])
    result = match_prices(bom, price, AS_OF)
    got = {(r["子件料號"], r["類型"]) for r in result.exceptions.to_dict("records") if r["是否阻擋"]}
    assert got == {("M-1", "幣別不一致"), ("M-2", "計價數量不支援")}


def test_required_columns_only_without_optional_columns():
    cols_b = BOM_COLS[:-1]
    cols_p = PRICE_COLS[:-1]
    bom = frame(cols_b, [["P-A", "A", "M-1", "x", "pcs", 1, 10]])
    price = frame(cols_p, [["M-1", "x", "pcs", "TWD", 12, D]])
    result = match_prices(bom, price, AS_OF)
    assert result.exceptions.empty
    assert result.matched_items.iloc[0]["適用單價"] == Decimal("12")


def test_quotes_from_two_suppliers_without_bom_supplier_block():
    bom = frame(BOM_COLS[:-1], [["P-A", "A", "M-1", "x", "pcs", 1, 10]])
    price = frame(PRICE_COLS, [
        ["M-1", "x", "pcs", "TWD", 12, D, "V-1"],
        ["M-1", "x", "pcs", "TWD", 11, D, "V-2"],
    ])
    result = match_prices(bom, price, AS_OF)
    assert set(result.exceptions["類型"]) == {"一料多供應商"}
    assert result.product_status.iloc[0]["狀態"] == INCOMPLETE
