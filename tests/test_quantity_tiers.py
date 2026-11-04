"""PR #23: quantity tiers and minimum price (spec section 4). Expected numbers are literals."""

import datetime as dt
import json
from decimal import Decimal
from pathlib import Path

import pytest

from core.batch_cost import MODE_DETAILED, MODE_EXISTING, CostModel, cost_model_for, read_batch_costs
from core.historical_quotes import HistoricalSource, import_historical_quotes
from core.quantity_tiers import (
    MAX_QUANTITIES,
    STATUS_BELOW_MOQ,
    STATUS_NO_COST,
    STATUS_OK,
    compute_quantity_tiers,
)
from tests.test_batch_cost import AS_OF, SAMPLE

ROOT = Path(__file__).resolve().parents[1]


def demo_model(fixed="1500"):
    return CostModel("P-DEMO", MODE_DETAILED, True, unit_variable=Decimal("180"),
                     batch_fixed=None if fixed is None else Decimal(fixed), basis="test", source="test")


def by_qty(result):
    return {r["數量"]: r for r in result.rows.to_dict("records")}


def test_acceptance_case_10_100_500():
    rows = by_qty(compute_quantity_tiers(demo_model(), [10, 100, 500], "0.20"))
    assert rows[10]["每件情境成本"] == Decimal("330") and rows[10]["安全底價（試算）"] == Decimal("412.50")
    assert rows[100]["每件情境成本"] == Decimal("195") and rows[100]["安全底價（試算）"] == Decimal("243.75")
    assert rows[500]["每件情境成本"] == Decimal("183") and rows[500]["安全底價（試算）"] == Decimal("228.75")
    assert rows[10]["每件分攤固定費"] == Decimal("150") and rows[500]["每件分攤固定費"] == Decimal("3")
    assert all(r["狀態"] == STATUS_OK for r in rows.values())


def test_non_terminating_allocation_rounds_floor_up():
    row = by_qty(compute_quantity_tiers(demo_model(), [7], "0.20"))[7]
    assert row["安全底價（試算）"] == Decimal("492.86")   # (180 + 1500/7) / 0.8 = 492.857...


def test_detailed_model_from_sample_file():
    model = cost_model_for("P-DEMO", MODE_DETAILED, AS_OF, batch=read_batch_costs(SAMPLE), version="A")
    assert by_qty(compute_quantity_tiers(model, [100], "0.20"))[100]["安全底價（試算）"] == Decimal("243.75")


def test_existing_mode_has_no_batch_allocation():
    model = CostModel("P-1001", MODE_EXISTING, True, unit_variable=Decimal("872.20"), batch_fixed=None, basis="x")
    rows = by_qty(compute_quantity_tiers(model, [10, 500], "0.15"))
    for q in (10, 500):
        assert rows[q]["每件分攤固定費"] is None and rows[q]["安全底價（試算）"] == Decimal("1026.12")
        assert "未計入批次固定費" in rows[q]["說明"]


def test_moq_blocks_lower_quantities():
    rows = by_qty(compute_quantity_tiers(demo_model(), [10, 50, 100], "0.20", moq=50))
    assert rows[10]["狀態"] == STATUS_BELOW_MOQ and rows[10]["安全底價（試算）"] is None
    assert rows[50]["狀態"] == STATUS_OK and rows[50]["安全底價（試算）"] == Decimal("262.50")  # (180 + 30) / 0.8


def test_unavailable_cost_gives_no_prices():
    model = CostModel("P-X", MODE_DETAILED, False, missing=["沒有批次成本"])
    rows = by_qty(compute_quantity_tiers(model, [10, 100], "0.20"))
    assert all(r["狀態"] == STATUS_NO_COST and r["安全底價（試算）"] is None for r in rows.values())
    assert all("沒有批次成本" in r["說明"] for r in rows.values())


@pytest.mark.parametrize("quantities", [[], [0], [-5], [10.5], ["abc"], [10, 10], list(range(1, MAX_QUANTITIES + 2))])
def test_invalid_quantities_are_rejected(quantities):
    with pytest.raises(ValueError):
        compute_quantity_tiers(demo_model(), quantities, "0.20")


@pytest.mark.parametrize("margin", ["1", "-0.1", "x"])
def test_invalid_margin_is_rejected(margin):
    with pytest.raises(ValueError):
        compute_quantity_tiers(demo_model(), [10], margin)


def test_zero_margin_and_sorted_output():
    rows = compute_quantity_tiers(demo_model(), [500, 10], "0").rows
    assert list(rows["數量"]) == [10, 500]
    assert list(rows["安全底價（試算）"]) == [Decimal("330.00"), Decimal("183.00")]


def test_history_difference_only_when_reference_exists():
    hist = ROOT / "samples" / "historical"
    sources = []
    for name, file in (("sales_dept", "historical_quotes_sales_dept.xlsx"),
                       ("legacy_system", "historical_quotes_legacy_system.xlsx")):
        m = json.loads((hist / f"mapping_{name}.json").read_text(encoding="utf-8"))["targets"]["HistoricalQuotes"]
        sources.append(HistoricalSource(file, (hist / file).read_bytes(), m["source_sheet"], m["columns"]))
    records = import_historical_quotes(sources).records
    model = CostModel("P-1001", MODE_EXISTING, True, unit_variable=Decimal("872.20"), batch_fixed=None, basis="x")
    rows = by_qty(compute_quantity_tiers(model, [10, 60], "0.15", history_records=records,
                                         as_of=dt.date(2026, 12, 15), drawing_version="B"))
    assert rows[60]["歷史中位數"] == Decimal("1050") and rows[60]["歷史筆數"] == 3
    assert rows[60]["底價與歷史中位數差額"] == Decimal("-23.88")      # 1026.12 - 1050
    assert rows[10]["歷史中位數"] is None and rows[10]["底價與歷史中位數差額"] is None
    assert "歷史資料不足" in rows[10]["說明"]


def test_no_market_price_wording():
    import inspect
    import core.quantity_tiers as qt
    text = inspect.getsource(qt)
    for word in ("最佳價格", "建議售價", "市場價格"):
        assert word not in text
