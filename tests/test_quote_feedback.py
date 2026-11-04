"""Quote result and actual-cost feedback (PR #34). Expected values are hand-derived:

100 pcs x 300 = revenue 30,000; estimated unit cost 200 x 100 = 20,000;
estimated margin (30,000-20,000)/30,000 = 33.33%.
Actual cost 22,500 -> profit 7,500, margin 7,500/30,000 = 25.00%,
cost increase 2,500, margin drop 33.333...-25 = 8.33 points.
"""

from decimal import Decimal

import pytest

from core.case_store import CaseStore, StoreError
from core.quote_feedback import (
    COST_ITEMS,
    STATUS_BLOCKED,
    STATUS_INCOMPLETE,
    STATUS_LOST,
    STATUS_NO_OUTCOME,
    STATUS_OK,
    analyze,
    record_outcome,
    validate_outcome,
)

D = Decimal


def _store(tmp_path):
    s = CaseStore(tmp_path / "cases.db", enabled=True)
    s.initialize()
    s.add_case({"case_id": "C1", "customer_code": "C-001", "rfq_no": "R1", "rfq_date": "2026-11-01",
                "status": "已報價", "source_file": "x.xlsx"},
               [{"line_no": "1", "product": "P-1", "quantity": D("100"), "unit": "PCS", "currency": "TWD"}],
               reason="test")
    s.add_quote_version("C1", "1", D("300"), D("100"), {"unit_cost": D("200")}, reason="首次報價")
    return s


QUOTE = {"unit_price": D("300"), "quantity": D("100"), "cost_snapshot": {"unit_cost": D("200")}}


def test_example_total_cost():
    r = analyze(QUOTE, {"result": "成交", "won_quantity": D("100"), "actual_quantity": D("100"),
                        "actual_total_cost": D("22500")})
    assert r["status"] == STATUS_OK
    assert r["estimated_revenue"] == D("30000")
    assert r["estimated_cost"] == D("20000")
    assert r["estimated_margin_pct"] == D("33.33")
    assert r["actual_cost"] == D("22500")
    assert r["actual_profit"] == D("7500")
    assert r["actual_margin_pct"] == D("25.00")
    assert r["cost_variance"] == D("2500")
    assert r["margin_drop_points"] == D("8.33")


def test_example_detail_cost_same_result():
    detail = {"材料": D("15000"), "人工": D("4000"), "製費": D("2500"), "委外": D("1000"), "其他": D("0")}
    assert set(detail) == set(COST_ITEMS)
    r = analyze(QUOTE, {"result": "成交", "won_quantity": D("100"), "actual_quantity": D("100"),
                        "actual_cost_detail": detail})
    assert r["status"] == STATUS_OK
    assert r["actual_cost"] == D("22500")
    assert r["actual_margin_pct"] == D("25.00")


def test_total_and_detail_are_exclusive():
    errors = validate_outcome({"result": "成交", "won_quantity": D("100"), "actual_quantity": D("100"),
                               "actual_total_cost": D("22500"), "actual_cost_detail": {"材料": D("1")}})
    assert any("擇一" in e for e in errors)


def test_incomplete_detail_gives_no_actual_margin():
    detail = {"材料": D("15000"), "人工": None, "製費": D("2500"), "委外": D("0"), "其他": D("0")}
    r = analyze(QUOTE, {"result": "成交", "won_quantity": D("100"), "actual_quantity": D("100"),
                        "actual_cost_detail": detail})
    assert r["status"] == STATUS_INCOMPLETE
    assert r["actual_margin_pct"] is None and r["actual_profit"] is None and r["actual_cost"] is None
    assert "人工" in r["message"]
    assert r["estimated_margin_pct"] == D("33.33")


def test_missing_detail_item_is_incomplete_not_zero():
    r = analyze(QUOTE, {"result": "成交", "won_quantity": D("100"), "actual_quantity": D("100"),
                        "actual_cost_detail": {"材料": D("22500")}})
    assert r["status"] == STATUS_INCOMPLETE


def test_no_actual_cost_is_incomplete():
    r = analyze(QUOTE, {"result": "成交", "won_quantity": D("100"), "actual_quantity": D("100")})
    assert r["status"] == STATUS_INCOMPLETE and r["actual_margin_pct"] is None


def test_lost_deal_refuses_actual_cost():
    errors = validate_outcome({"result": "未成交", "actual_total_cost": D("1000")})
    assert any("未成交" in e for e in errors)
    assert validate_outcome({"result": "未成交", "lost_reason": "價格"}) == []
    r = analyze(QUOTE, {"result": "未成交", "lost_reason": "價格"})
    assert r["status"] == STATUS_LOST and r["actual_cost"] is None


@pytest.mark.parametrize("won,actual", [(D("80"), D("80")), (D("100"), D("120"))])
def test_quantity_scope_mismatch_blocks(won, actual):
    r = analyze(QUOTE, {"result": "成交", "won_quantity": won, "actual_quantity": actual,
                        "actual_total_cost": D("22500")})
    assert r["status"] == STATUS_BLOCKED
    assert r["actual_margin_pct"] is None and r["actual_cost"] is None
    assert "不分攤" in r["message"]


def test_invalid_values():
    assert validate_outcome({"result": "其他"})
    assert validate_outcome({"result": "成交", "won_quantity": D("0"), "actual_quantity": D("0")})
    assert validate_outcome({"result": "成交", "won_quantity": D("100"), "actual_quantity": D("100"),
                             "actual_total_cost": D("-1")})
    assert validate_outcome({"result": "成交", "won_quantity": D("100"), "actual_quantity": D("100"),
                             "actual_cost_detail": {"不明項目": D("1")}})


def test_snapshot_without_unit_cost_has_no_estimate():
    q = dict(QUOTE, cost_snapshot={})
    r = analyze(q, {"result": "成交", "won_quantity": D("100"), "actual_quantity": D("100"),
                    "actual_total_cost": D("22500")})
    assert r["estimated_margin_pct"] is None and r["margin_drop_points"] is None
    assert r["actual_margin_pct"] == D("25.00")


def test_no_outcome():
    assert analyze(QUOTE, None)["status"] == STATUS_NO_OUTCOME


def test_record_outcome_appends_revisions_and_keeps_snapshot(tmp_path):
    s = _store(tmp_path)
    data = {"result": "成交", "won_quantity": D("100"), "actual_quantity": D("100"), "actual_total_cost": D("22000")}
    assert record_outcome(s, "C1", "1", 1, data, reason="初次回填") == 1
    data2 = dict(data, actual_total_cost=D("22500"))
    assert record_outcome(s, "C1", "1", 1, data2, reason="補登委外費用") == 2
    revs = s.outcomes("C1", "1", 1)
    assert [r["revision"] for r in revs] == [1, 2]
    assert revs[0]["data"]["actual_total_cost"] == D("22000")
    assert revs[1]["data"]["actual_total_cost"] == D("22500")
    assert s.quote_versions("C1", "1")[0]["cost_snapshot"] == {"unit_cost": D("200")}
    actions = [e["action"] for e in s.events("C1")]
    assert actions.count("回填結果") == 2


def test_record_outcome_validates_and_requires_reason(tmp_path):
    s = _store(tmp_path)
    with pytest.raises(StoreError):
        record_outcome(s, "C1", "1", 1, {"result": "未成交", "actual_total_cost": D("1")}, reason="x")
    with pytest.raises(StoreError):
        record_outcome(s, "C1", "1", 1, {"result": "未成交"}, reason=" ")
    with pytest.raises(StoreError):
        record_outcome(s, "C1", "1", 9, {"result": "未成交"}, reason="不存在的版本")
    assert s.outcomes("C1", "1", 1) == []
