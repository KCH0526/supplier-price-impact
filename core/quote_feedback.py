"""Quote result and actual-cost feedback, with estimated-vs-actual variance (PR #34).

Rules (docs/PRODUCTION_QUOTING_ROADMAP.md section 7):
- The estimate always comes from the cost snapshot saved with the quote version;
  it is never recomputed from today's BOM.
- Actual cost is either one total (for the actual quantity) or a full detail
  breakdown, never both. A blank detail item is unknown, not 0.
- Incomplete actual cost -> no actual profit or margin.
- A lost deal has no actual cost.
- Quoted, won and actual-cost quantities must be the same; otherwise the
  variance is blocked. Costs are never allocated between quantities.
- Outcomes are append-only revisions; earlier revisions are kept.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from core.case_store import CaseStore, StoreError

RESULTS = ("成交", "未成交")
COST_ITEMS = ("材料", "人工", "製費", "委外", "其他")
STATUS_OK = "可分析"
STATUS_INCOMPLETE = "成本不完整"
STATUS_BLOCKED = "數量口徑不一致"
STATUS_LOST = "未成交"
STATUS_NO_OUTCOME = "尚無結果"
_COST_KEYS = ("actual_total_cost", "actual_cost_detail")


def _pct(numerator: Decimal, denominator: Decimal) -> Decimal:
    return numerator / denominator * 100


def _round2(v):
    return None if v is None else v.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _dec(v):
    return v if isinstance(v, Decimal) else None


def validate_outcome(data: dict) -> list[str]:
    """Blocking problems that prevent saving this outcome (empty list = OK)."""
    errors = []
    result = data.get("result")
    if result not in RESULTS:
        return [f"結果必須是「成交」或「未成交」，收到「{result}」"]
    has_total = data.get("actual_total_cost") is not None
    has_detail = bool(data.get("actual_cost_detail"))
    if result == "未成交":
        if has_total or has_detail or data.get("won_quantity") is not None or data.get("actual_quantity") is not None:
            errors.append("未成交的案件不可填寫成交數量或實際成本")
        return errors
    for key, label in (("won_quantity", "成交數量"), ("actual_quantity", "實際成本對應數量")):
        v = data.get(key)
        if v is not None and (not isinstance(v, Decimal) or v <= 0):
            errors.append(f"{label}必須是大於 0 的數字")
    if data.get("won_quantity") is None:
        errors.append("成交必須填寫成交數量")
    if has_total and has_detail:
        errors.append("實際總成本與明細成本只能擇一填寫，避免重複加總")
    if has_total:
        t = data["actual_total_cost"]
        if not isinstance(t, Decimal) or t < 0:
            errors.append("實際總成本必須是 0 以上的數字")
    if has_detail:
        for k, v in data["actual_cost_detail"].items():
            if k not in COST_ITEMS:
                errors.append(f"未知的成本項目「{k}」；可用：{'、'.join(COST_ITEMS)}")
            elif v is not None and (not isinstance(v, Decimal) or v < 0):
                errors.append(f"成本項目「{k}」必須是 0 以上的數字或空白（未知）")
    if (has_total or has_detail) and data.get("actual_quantity") is None:
        errors.append("填寫實際成本時，必須填寫這筆成本對應的數量")
    return errors


def _empty(status, message):
    keys = ("estimated_revenue", "estimated_cost", "estimated_margin_pct", "actual_cost", "actual_profit",
            "actual_margin_pct", "cost_variance", "margin_drop_points")
    return dict({k: None for k in keys}, status=status, message=message)


def analyze(quote: dict, outcome: dict | None) -> dict:
    """Estimated vs actual for one quote version and its latest outcome data."""
    price, qty = _dec(quote.get("unit_price")), _dec(quote.get("quantity"))
    unit_cost = _dec((quote.get("cost_snapshot") or {}).get("unit_cost"))
    est = {}
    if price is not None and qty is not None and qty > 0:
        est["estimated_revenue"] = price * qty
        if unit_cost is not None:
            est["estimated_cost"] = unit_cost * qty
            if est["estimated_revenue"] > 0:
                est["estimated_margin_pct"] = _pct(est["estimated_revenue"] - est["estimated_cost"],
                                                   est["estimated_revenue"])

    def done(status, message, **actual):
        r = _empty(status, message)
        r.update(est)
        r.update(actual)
        raw_est, raw_act = r["estimated_margin_pct"], r["actual_margin_pct"]
        if raw_est is not None and raw_act is not None:
            r["margin_drop_points"] = _round2(raw_est - raw_act)
        if r["estimated_cost"] is not None and r["actual_cost"] is not None:
            r["cost_variance"] = r["actual_cost"] - r["estimated_cost"]
        r["estimated_margin_pct"] = _round2(raw_est)
        r["actual_margin_pct"] = _round2(raw_act)
        return r

    if not outcome:
        return done(STATUS_NO_OUTCOME, "尚未回填報價結果")
    errors = validate_outcome(outcome)
    if errors:
        return done(STATUS_BLOCKED if outcome.get("result") == "成交" else STATUS_LOST, "；".join(errors))
    if outcome["result"] == "未成交":
        return done(STATUS_LOST, "未成交，不計算實際成本")
    won, act_qty = outcome.get("won_quantity"), outcome.get("actual_quantity")
    if act_qty is not None and (won != qty or act_qty != won):
        return done(STATUS_BLOCKED, f"報價數量 {qty}、成交數量 {won}、實際成本數量 {act_qty} 不一致；"
                                    "系統不分攤成本，請以相同數量口徑回填")
    if won != qty:
        return done(STATUS_BLOCKED, f"報價數量 {qty} 與成交數量 {won} 不一致；系統不分攤成本")
    if outcome.get("actual_total_cost") is not None:
        actual = outcome["actual_total_cost"]
    elif outcome.get("actual_cost_detail"):
        detail = outcome["actual_cost_detail"]
        missing = [k for k in COST_ITEMS if detail.get(k) is None]
        if missing:
            return done(STATUS_INCOMPLETE, f"實際成本不完整（{'、'.join(missing)} 未填；空白不視為 0），不計算實際毛利率")
        actual = sum((detail[k] for k in COST_ITEMS), Decimal("0"))
    else:
        return done(STATUS_INCOMPLETE, "尚未填寫實際成本，不計算實際毛利率")
    revenue = price * qty if price is not None else None
    profit = revenue - actual if revenue is not None else None
    margin = _pct(profit, revenue) if revenue else None
    return done(STATUS_OK, "可比較預估與實際", actual_cost=actual, actual_profit=profit, actual_margin_pct=margin)


def record_outcome(store: CaseStore, case_id, line_no, version: int, data: dict, reason: str,
                   source: str | None = None) -> int:
    """Validate, then append a new outcome revision (earlier revisions are kept)."""
    errors = validate_outcome(data)
    if errors:
        raise StoreError("；".join(errors))
    return store.add_outcome(case_id, line_no, version, data, reason=reason, source=source)
