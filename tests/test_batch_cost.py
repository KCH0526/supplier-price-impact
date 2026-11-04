"""PR #22: batch cost model with two mutually exclusive modes (spec section 3)."""

import datetime as dt
from decimal import Decimal
from pathlib import Path

import pytest

from core.batch_cost import (
    BATCH_REQUIRED,
    MODE_DETAILED,
    MODE_EXISTING,
    cost_model_for,
    read_batch_costs,
)
from core.calculator import calculate_cost_impact
from core.field_mapper import TARGETS
from core.matcher import match_prices
from core.reader import read_bom, read_price_increase, read_sheet
from core.validation import ERROR, WARNING

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "samples" / "batch_cost" / "batch_cost_sample.xlsx"
EDGE = ROOT / "tests" / "fixtures" / "batch_cost_edge_cases.xlsx"
AS_OF = dt.date(2026, 12, 1)


@pytest.fixture(scope="module")
def existing_costs():
    bom = ROOT / "samples" / "sample_bom.xlsx"
    matched = match_prices(read_bom(bom).data, read_price_increase(ROOT / "samples" / "sample_price_increase.xlsx").data, AS_OF)
    return calculate_cost_impact(matched, read_sheet(bom, "ProductCost", ["成品編號"]).data)


def test_schema_and_mapping_target():
    assert BATCH_REQUIRED[:5] == ["成品編號", "成本基準日", "幣別", "單位", "單件材料變動成本"]
    assert TARGETS["BatchCost"].required == BATCH_REQUIRED


def test_detailed_mode_sums_variable_and_fixed_costs():
    table = read_batch_costs(SAMPLE)
    assert [i for i in table.issues if i.severity == ERROR] == []
    m = cost_model_for("P-DEMO", MODE_DETAILED, AS_OF, batch=table, version="A")
    assert m.available is True
    assert m.unit_variable == Decimal("180")          # 100 + 40 + 30 + 10
    assert m.batch_fixed == Decimal("1500")           # 1000 + 500 + 0
    assert m.components["單件委外加工費"] == Decimal("10")
    assert "samples" not in m.source and "合成示範" in m.source


def test_existing_mode_never_adds_batch_fees(existing_costs):
    m = cost_model_for("P-1001", MODE_EXISTING, AS_OF, costs=existing_costs)
    assert m.available is True
    assert m.unit_variable == Decimal("872.20") and m.batch_fixed is None
    assert "未計入批次固定費" in m.basis


def test_modes_do_not_mix(existing_costs):
    # P-1001 has both a complete existing cost and a detailed record; each mode uses only its own source.
    table = read_batch_costs(SAMPLE)
    a = cost_model_for("P-1001", MODE_EXISTING, AS_OF, costs=existing_costs, batch=table, version="B")
    b = cost_model_for("P-1001", MODE_DETAILED, AS_OF, costs=existing_costs, batch=table, version="B")
    assert (a.unit_variable, a.batch_fixed) == (Decimal("872.20"), None)
    assert (b.unit_variable, b.batch_fixed) == (Decimal("890"), Decimal("1800"))   # 620+170+100+0, 1200+600+0
    with pytest.raises(ValueError):
        cost_model_for("P-1001", "混合", AS_OF, costs=existing_costs, batch=table)


def test_existing_mode_needs_complete_full_cost():
    bom = ROOT / "samples" / "sample_bom.xlsx"
    matched = match_prices(read_bom(bom).data, read_price_increase(ROOT / "samples" / "sample_price_increase.xlsx").data, AS_OF)
    material_only = calculate_cost_impact(matched, None)
    m = cost_model_for("P-1001", MODE_EXISTING, AS_OF, costs=material_only)
    assert m.available is False and m.unit_variable is None and any("人工" in x for x in m.missing)
    assert cost_model_for("P-1001", MODE_EXISTING, AS_OF, costs=None).available is False


def _issues(table, row):
    return [i for i in table.issues if i.row == row]


def test_edge_rows():
    t = read_batch_costs(EDGE)
    assert any(i.column == "單件人工變動成本" and "空白" in i.reason for i in _issues(t, 3))
    assert any(i.column == "成本完整性狀態" for i in _issues(t, 4))
    assert any(i.column == "幣別" for i in _issues(t, 5))
    assert any(i.column == "單位" for i in _issues(t, 6))
    assert any(i.column == "單件製造費用" for i in _issues(t, 11))
    dup = [i for i in t.issues if "重複" in i.reason]
    assert {i.row for i in dup} == {9, 10} and all(i.severity == ERROR for i in dup)
    for product in ("E-BLANK", "E-UNCONF", "E-USD", "E-KG", "E-DUP", "E-NEG"):
        m = cost_model_for(product, MODE_DETAILED, AS_OF, batch=t, version="A")
        assert m.available is False and m.unit_variable is None, product


def test_explicit_zero_is_valid_and_blank_is_not():
    t = read_batch_costs(EDGE)
    ok = cost_model_for("E-OK", MODE_DETAILED, AS_OF, batch=t, version="A")
    assert ok.available and ok.components["單件委外加工費"] == Decimal("0")
    assert ok.unit_variable == Decimal("170") and ok.batch_fixed == Decimal("1500")


def test_base_date_rules():
    t = read_batch_costs(EDGE)
    fut = cost_model_for("E-FUT", MODE_DETAILED, AS_OF, batch=t, version="A")
    assert fut.available is False and any("晚於試算日" in x for x in fut.missing)
    old = cost_model_for("E-OLD", MODE_DETAILED, AS_OF, batch=t, version="A")
    assert old.available is True and any("365" in w for w in old.warnings)


def test_version_must_match_and_is_not_guessed():
    t = read_batch_costs(SAMPLE)
    m = cost_model_for("P-DEMO", MODE_DETAILED, AS_OF, batch=t, version="Z")
    assert m.available is False and any("版次" in x for x in m.missing)
    assert cost_model_for("P-NONE", MODE_DETAILED, AS_OF, batch=t).available is False
    assert cost_model_for("P-DEMO", MODE_DETAILED, AS_OF, batch=None, version="A").available is False


def test_issue_severity_for_old_base_date_is_warning():
    t = read_batch_costs(EDGE)
    assert all(i.severity == WARNING for i in _issues(t, 8))
