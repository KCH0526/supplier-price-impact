"""Tests for core.quote_risk. Expected values are literal, independently derived numbers."""

import datetime as dt
import time
from decimal import Decimal

import pandas as pd
import pytest

from core.calculator import calculate_cost_impact
from core.matcher import match_prices
from core.quote_reader import QUOTE_REQUIRED_COLUMNS, read_open_quotes
from core.quote_risk import (
    STATUS_EXCLUDED,
    STATUS_OK,
    STATUS_REVIEW,
    STATUS_UNRELIABLE,
    assess_quote_risk,
)
from core.reader import read_bom, read_price_increase, read_sheet
from tests.test_quote_reader import EDGE_QUOTES, SAMPLE_QUOTES
from tests.test_reader import EDGE_BOM, EDGE_PRICE, SAMPLE_BOM, SAMPLE_PRICE

AS_OF = dt.date(2026, 12, 1)
D1, D2 = dt.datetime(2026, 11, 1), dt.datetime(2027, 1, 31)


def costs(bom=SAMPLE_BOM, price=SAMPLE_PRICE, with_product_cost=True):
    details = read_sheet(bom, "ProductCost", ["成品編號"]).data if with_product_cost else None
    matched = match_prices(read_bom(bom).data, read_price_increase(price).data, AS_OF)
    return calculate_cost_impact(matched, details)


@pytest.fixture(scope="module")
def full_costs():
    return costs()


def quotes(rows):
    base = dict(zip(QUOTE_REQUIRED_COLUMNS, ["Q-1", "1", "P-1001", "C-001", 1000, "TWD", 50, D1, D2, "有效"]))
    records = []
    for i, change in enumerate(rows):
        rec = dict(base, 行號=str(i + 1))
        rec.update(change)
        records.append([rec[c] for c in QUOTE_REQUIRED_COLUMNS])
    df = pd.DataFrame(records, columns=QUOTE_REQUIRED_COLUMNS, dtype=object)
    df.insert(0, "excel_row", range(2, 2 + len(df)))
    return df


def one(result, row=2):
    return result.risk[result.risk["來源Excel列號"] == row].iloc[0]


def near(value, expected, places=4):
    return abs(Decimal(value) - Decimal(expected)) < Decimal(10) ** -places


# ---------- acceptance cases ----------

def test_case_a_p1001(full_costs):
    r = one(assess_quote_risk(quotes([{}]), full_costs, AS_OF, Decimal("0.15")))
    assert r["原完整成本"] == Decimal("836.60")
    assert r["新完整成本"] == Decimal("872.20")
    assert near(r["原毛利率"], "0.1634")
    assert near(r["新毛利率"], "0.1278")
    assert near(r["毛利率下降百分點"], "3.56")
    assert r["報價情境成本增加"] == Decimal("1780.00")
    assert r["維持底線所需最低單價"] == Decimal("1026.12")
    assert r["設定毛利率底線"] == Decimal("0.15")
    assert r["覆核狀態"] == STATUS_REVIEW
    assert "12.78%" in r["問題原因"] and "15.00%" in r["問題原因"]


def test_case_b_p1002_floor_20(full_costs):
    q = quotes([{"成品編號": "P-1002", "未稅報價單價": 450, "報價數量": 10}])
    r = one(assess_quote_risk(q, full_costs, AS_OF, Decimal("0.20")))
    assert near(r["新毛利率"], "0.346222", 6)
    assert r["報價情境成本增加"] == Decimal("114.50")
    assert r["覆核狀態"] == STATUS_OK
    assert "成本增加" in r["問題原因"]  # still shown although above the floor


def test_default_floor_is_15_percent(full_costs):
    r = one(assess_quote_risk(quotes([{}]), full_costs, AS_OF))
    assert r["設定毛利率底線"] == Decimal("0.15")


# ---------- minimum price rounding ----------

def test_minimum_price_is_rounded_up_not_half_up(full_costs):
    # 872.20 / 0.85 = 1026.1176...; half-up would also give 1026.12, so use a
    # floor where half-up would round DOWN: 872.20 / (1 - 0.1) = 969.1111...
    r = one(assess_quote_risk(quotes([{}]), full_costs, AS_OF, Decimal("0.10")))
    assert r["維持底線所需最低單價"] == Decimal("969.12")
    price, cost, floor = r["維持底線所需最低單價"], Decimal("872.20"), Decimal("0.10")
    assert (price - cost) / price >= floor


def test_minimum_price_exact_value_is_not_increased(full_costs):
    # 872.20 / (1 - 0.2) = 1090.25 exactly
    r = one(assess_quote_risk(quotes([{}]), full_costs, AS_OF, Decimal("0.2")))
    assert r["維持底線所需最低單價"] == Decimal("1090.25")


@pytest.mark.parametrize("floor", ["0", "0.0", 0])
def test_zero_floor(full_costs, floor):
    r = one(assess_quote_risk(quotes([{}]), full_costs, AS_OF, floor))
    assert r["維持底線所需最低單價"] == Decimal("872.20")
    assert r["覆核狀態"] == STATUS_OK


def test_floor_close_to_100_percent(full_costs):
    r = one(assess_quote_risk(quotes([{}]), full_costs, AS_OF, Decimal("0.999")))
    assert r["維持底線所需最低單價"] == Decimal("872200.00")
    assert r["覆核狀態"] == STATUS_REVIEW


@pytest.mark.parametrize("floor", [Decimal("1"), Decimal("-0.01"), Decimal("1.5"), "abc", None, float("nan")])
def test_invalid_floor_is_rejected(full_costs, floor):
    with pytest.raises(ValueError):
        assess_quote_risk(quotes([{}]), full_costs, AS_OF, floor)


def test_as_of_is_required(full_costs):
    with pytest.raises(TypeError):
        assess_quote_risk(quotes([{}]), full_costs)


# ---------- review logic ----------

def test_already_below_floor_before_increase(full_costs):
    q = quotes([{"成品編號": "P-1003", "未稅報價單價": 600, "報價數量": 10}])
    r = one(assess_quote_risk(q, full_costs, AS_OF))
    assert r["覆核狀態"] == STATUS_REVIEW
    assert near(r["原毛利率"], "0.085")
    assert "調價前已低於" in r["問題原因"]


def test_below_floor_only_after_increase(full_costs):
    q = quotes([{"成品編號": "P-1005", "未稅報價單價": 800, "報價數量": 40}])
    r = one(assess_quote_risk(q, full_costs, AS_OF))
    assert near(r["原毛利率"], "0.17475") and near(r["新毛利率"], "0.14425")
    assert r["報價情境成本增加"] == Decimal("976.00")
    assert r["覆核狀態"] == STATUS_REVIEW
    assert "漲價後" in r["問題原因"]


def test_cost_decrease_gives_negative_scenario_amount():
    # Edge fixtures: only M-209 (20 -> 17) and M-212 are usable; build a clean
    # product whose single component got cheaper.
    bom = pd.DataFrame([["P-D", "降價品", "M-1", "x", "pcs", 2, 20]],
                       columns=["成品編號", "成品名稱", "子件料號", "子件名稱", "單位", "用量", "原單價"], dtype=object)
    bom.insert(0, "excel_row", [2])
    price = pd.DataFrame([["M-1", "x", "pcs", "TWD", 17, D1]],
                         columns=["子件料號", "子件名稱", "單位", "幣別", "新單價", "生效日"], dtype=object)
    price.insert(0, "excel_row", [2])
    product_cost = pd.DataFrame([{"成品編號": "P-D", "單件人工成本": 10, "單件製造費用": 5, "單件其他成本": 0}])
    c = calculate_cost_impact(match_prices(bom, price, AS_OF), product_cost)
    q = quotes([{"成品編號": "P-D", "未稅報價單價": 100, "報價數量": 10}])
    r = one(assess_quote_risk(q, c, AS_OF))
    assert r["原完整成本"] == Decimal("55") and r["新完整成本"] == Decimal("49")
    assert r["報價情境成本增加"] == Decimal("-60")
    assert near(r["毛利率下降百分點"], "-6")
    assert r["覆核狀態"] == STATUS_OK
    assert "成本下降" in r["問題原因"]


def test_same_product_many_customer_quotes_are_independent(full_costs):
    q = quotes([{"客戶代碼": "C-001", "未稅報價單價": 1000, "報價數量": 50},
                {"客戶代碼": "C-005", "未稅報價單價": 1150, "報價數量": 20}])
    res = assess_quote_risk(q, full_costs, AS_OF)
    assert one(res, 2)["覆核狀態"] == STATUS_REVIEW
    assert one(res, 3)["覆核狀態"] == STATUS_OK
    assert one(res, 3)["報價情境成本增加"] == Decimal("712.00")


# ---------- unreliable / excluded ----------

@pytest.mark.parametrize("change, status", [
    ({"報價狀態": "已取消"}, STATUS_EXCLUDED),
    ({"生效日": dt.datetime(2026, 12, 2)}, STATUS_EXCLUDED),        # not yet effective
    ({"截止日": dt.datetime(2026, 11, 30)}, STATUS_EXCLUDED),       # expired
    ({"未稅報價單價": None}, STATUS_UNRELIABLE),
    ({"未稅報價單價": 0}, STATUS_UNRELIABLE),
    ({"報價數量": -5}, STATUS_UNRELIABLE),
    ({"報價幣別": "USD"}, STATUS_UNRELIABLE),
    ({"報價狀態": None}, STATUS_UNRELIABLE),
    ({"成品編號": "P-9999"}, STATUS_UNRELIABLE),
])
def test_quote_level_problems_give_no_margin_numbers(full_costs, change, status):
    res = assess_quote_risk(quotes([change]), full_costs, AS_OF)
    r = one(res)
    assert r["覆核狀態"] == status
    assert r["問題原因"]
    for col in ("原毛利率", "新毛利率", "毛利率下降百分點", "報價情境成本增加", "維持底線所需最低單價"):
        assert r[col] is None, col
    assert len(res.exceptions[res.exceptions["Excel列號"] == 2]) >= 1


def test_validity_window_includes_both_end_days(full_costs):
    q = quotes([{"生效日": dt.datetime(2026, 12, 1), "截止日": dt.datetime(2026, 12, 1)}])
    assert one(assess_quote_risk(q, full_costs, AS_OF))["覆核狀態"] == STATUS_REVIEW


def test_duplicate_quote_key_blocks_both_rows_others_continue(full_costs):
    q = quotes([{}, {}, {"成品編號": "P-1006", "未稅報價單價": 690, "報價數量": 100}])
    q.loc[1, "行號"] = "1"
    res = assess_quote_risk(q, full_costs, AS_OF)
    assert one(res, 2)["覆核狀態"] == STATUS_UNRELIABLE
    assert one(res, 3)["覆核狀態"] == STATUS_UNRELIABLE
    assert one(res, 4)["覆核狀態"] == STATUS_OK
    assert one(res, 4)["報價情境成本增加"] == Decimal("1500.00")


def test_material_only_costs_are_unreliable():
    c = costs(with_product_cost=False)  # no labour / overhead
    r = one(assess_quote_risk(quotes([{}]), c, AS_OF))
    assert r["覆核狀態"] == STATUS_UNRELIABLE
    assert "人工" in r["問題原因"]
    assert r["新毛利率"] is None


def test_incomplete_bom_cost_is_unreliable_never_zero():
    c = costs(EDGE_BOM, EDGE_PRICE, with_product_cost=False)
    q = quotes([{"成品編號": "P-X01", "未稅報價單價": 500, "報價數量": 5}])
    r = one(assess_quote_risk(q, c, AS_OF))
    assert r["覆核狀態"] == STATUS_UNRELIABLE
    assert "不完整" in r["問題原因"]
    assert r["原完整成本"] is None and r["新完整成本"] is None


# ---------- fixtures, ordering, ids ----------

EDGE_STATUS = {
    2: STATUS_REVIEW, 3: STATUS_UNRELIABLE, 4: STATUS_UNRELIABLE, 5: STATUS_EXCLUDED,
    6: STATUS_UNRELIABLE, 7: STATUS_UNRELIABLE, 8: STATUS_UNRELIABLE, 9: STATUS_UNRELIABLE,
    10: STATUS_EXCLUDED, 11: STATUS_EXCLUDED, 12: STATUS_UNRELIABLE, 13: STATUS_REVIEW,
    14: STATUS_REVIEW, 15: STATUS_OK, 16: STATUS_UNRELIABLE, 17: STATUS_UNRELIABLE,
}


def test_edge_fixture_statuses(full_costs):
    res = assess_quote_risk(read_open_quotes(EDGE_QUOTES).data, full_costs, AS_OF)
    assert dict(zip(res.risk["來源Excel列號"], res.risk["覆核狀態"])) == EDGE_STATUS


def test_leading_zero_ids_are_kept(full_costs):
    res = assess_quote_risk(read_open_quotes(EDGE_QUOTES).data, full_costs, AS_OF)
    r = one(res, 15)
    assert (r["報價單號"], r["行號"], r["客戶代碼"]) == ("000777", "01", "00125")


def test_sample_quotes_summary_and_risk_order(full_costs):
    res = assess_quote_risk(read_open_quotes(SAMPLE_QUOTES).data, full_costs, AS_OF)
    statuses = list(res.risk["覆核狀態"])
    assert statuses == [STATUS_REVIEW] * 3 + [STATUS_OK] * 4 + [STATUS_EXCLUDED]
    # Highest risk first: the larger shortfall below the floor comes first.
    assert list(res.risk["成品編號"][:3]) == ["P-1003", "P-1001", "P-1005"]
    assert list(res.risk["風險排序"]) == list(range(1, 9))
    s = res.summary
    assert (s["需人工覆核"], s["尚符合設定底線"], s["無法可靠判斷"], s["不納入試算"]) == (3, 4, 0, 1)
    # 1780 + 114.50 + 510 + 888 + 976 + 1500 + 712 (cancelled excluded)
    assert s["報價情境成本增加合計"] == Decimal("6480.50")
    assert s["需人工覆核報價情境成本增加合計"] == Decimal("3266.00")


def test_no_quadratic_slowdown(full_costs):
    def run(n):
        rows = [{"報價單號": f"Q-{i}", "成品編號": f"P-100{i % 6 + 1}"} for i in range(n)]
        q = quotes(rows)
        start = time.perf_counter()
        assess_quote_risk(q, full_costs, AS_OF)
        return time.perf_counter() - start
    small, large = run(500), run(5000)
    assert large < small * 30 + 0.5  # linear would be ~10x
