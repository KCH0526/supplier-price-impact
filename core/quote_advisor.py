"""Quote recommendation and price warnings (PR #18).

Rules: docs/HISTORICAL_QUOTE_PRODUCT_SPEC.md section 6. Three things are
kept apart:

A. Cost safety floor - only from a COMPLETE full cost (existing calculator):
   new full unit cost / (1 - target margin), rounded UP to the cent.
B. Historical reference - the statistics of core.quote_search; historical
   quotes are not deal prices.
C. Review status, warnings and missing data. Never a price commitment,
   discount, deal-probability estimate or automatic sending.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from decimal import Decimal

import pandas as pd

from core.calculator import FULL_BASIS, CostResult
from core.matcher import COMPLETE
from core.quote_risk import ceil_cent, parse_min_margin
from core.quote_search import INCLUDED, INSUFFICIENT, SearchResult
from core.validation import is_blank, parse_number

INTERNAL_LABEL = "僅供內部試算，需人工核准"
STATUS_NO_FLOOR = "無法提供安全底價"
STATUS_INSUFFICIENT = "歷史資料不足"
STATUS_BELOW_FLOOR = "歷史價格低於安全底線"
STATUS_REFERENCE = "可參考歷史區間"
SPREAD_LIMIT = Decimal("0.30")
COST_UNIT = "pcs"
HIGH, MEDIUM = "高", "中"


@dataclass
class Advice:
    status: str
    message: str
    floor: dict
    reference: dict | None
    warnings: list[dict] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    evidence: pd.DataFrame | None = None
    query: dict = field(default_factory=dict)
    label: str = INTERNAL_LABEL


def _pct(value: Decimal) -> str:
    return f"{(value * 100).quantize(Decimal('0.01'))}%"


def _floor(costs: CostResult, product: str, unit: str, margin: Decimal) -> tuple[dict, list[str]]:
    floor = {"可用": False, "新完整成本": None, "原完整成本": None, "目標毛利率": margin, "安全底價": None,
             "計算式": None}
    rows = {r["成品編號"]: r for r in costs.cost_impact.to_dict("records")}
    row = rows.get(product)
    if row is None:
        return floor, [f"成品「{product}」不在目前的 BOM 試算結果中，沒有成本"]
    if row["試算狀態"] != COMPLETE or row["新成本"] is None:
        return floor, [f"成品「{product}」有阻擋例外，成本不完整；請先處理 BOM／供應商報價例外"]
    if row["成本口徑"] != FULL_BASIS:
        return floor, [f"成品「{product}」缺少人工、製造費用或其他成本，只有材料成本"]
    if unit != COST_UNIT:
        return floor, [f"成本以每件（{COST_UNIT}）計算，查詢的計價單位是「{unit}」，無法直接換算"]
    new, old = Decimal(row["新成本"]), Decimal(row["原成本"])
    price = ceil_cent(new / (1 - margin))
    floor.update({"可用": True, "新完整成本": new, "原完整成本": old, "安全底價": price,
                  "計算式": f"{new} ÷ (1 − {margin}) = {new / (1 - margin):.4f}，無條件進位為 {price}"})
    return floor, []


def advise_quote(search: SearchResult, records: pd.DataFrame, costs: CostResult, target_margin,
                 price_increase_date: dt.date | None = None, proposed_price=None) -> Advice:
    margin = parse_min_margin(target_margin)
    q = search.query
    product, unit, as_of, version = q["成品編號"], q["計價單位"], q["試算日"], q["圖面版次"]
    floor, missing = _floor(costs, product, unit, margin)
    warnings: list[dict] = []

    def warn(kind, level, text, basis=""):
        warnings.append({"類型": kind, "嚴重度": level, "說明": text, "依據": basis})

    evidence = search.candidates[search.candidates["判定"] == INCLUDED].copy() if not search.candidates.empty \
        else search.candidates
    stats = search.stats

    if not floor["可用"]:
        warn("缺少目前完整成本", HIGH, "；".join(missing) + "。因此無法提供可靠的最低售價")
    if search.status == INSUFFICIENT:
        warn("歷史資料品質不足", MEDIUM, search.message)

    if floor["可用"] and stats:
        low = [r for r in evidence.to_dict("records") if r["報價單價"] < floor["安全底價"]]
        if low:
            basis = "、".join(f"{r['報價單號']}/{r['報價行號']}（{r['報價單價']}）" for r in low)
            warn("歷史價格低於安全底線", HIGH,
                 f"歷史相似案件的低價 {stats['最低']} 低於目前安全底價 {floor['安全底價']}"
                 f"（目標毛利率 {_pct(margin)}），建議不得直接沿用舊價", basis)
    if stats and stats["中位數"] > 0:
        spread = (stats["最高"] - stats["最低"]) / stats["中位數"]
        if spread > SPREAD_LIMIT:
            warn("同條件價格差異過大", MEDIUM,
                 f"可比較報價最高 {stats['最高']}、最低 {stats['最低']}，差距為中位數的 {_pct(spread)}"
                 f"（超過 {_pct(SPREAD_LIMIT)}），請確認報價條件是否真的相同")

    same = records[(records["成品編號"] == product)]
    usable = same[(same["可直接比較"] == True) & (same["最新版本"] == True)]  # noqa: E712
    other_units = sorted(set(usable["計價單位"]) - {unit})
    if other_units:
        warn("價格單位不一致", MEDIUM,
             f"同成品另有以 {'、'.join(other_units)} 計價的歷史報價，已排除，不做單位換算")

    usable = usable[(usable["計價單位"] == unit) & usable["報價日期"].map(lambda d: d.date() <= as_of)]
    if version is not None and not usable.empty:
        latest = usable.sort_values("報價日期").iloc[-1]
        if latest["規格圖面版次"] != version:
            shown = latest["規格圖面版次"] or "未知"
            warn("舊版價格風險", HIGH,
                 f"最近一筆報價使用圖面版次 {shown}，與本次指定的 {version} 不同；不可直接沿用該價格",
                 f"{latest['報價單號']}/{latest['報價行號']}（{latest['報價日期'].date()}）")

    if price_increase_date is not None and not usable.empty:
        before = usable[usable["報價日期"].map(lambda d: d.date() < price_increase_date)]
        after = usable[usable["報價日期"].map(lambda d: d.date() >= price_increase_date)]
        if not before.empty:
            prev = before.sort_values("報價日期").iloc[-1]
            for r in after.to_dict("records"):
                if r["報價單價"] == prev["報價單價"]:
                    note = ""
                    if floor["可用"] and floor["新完整成本"] > floor["原完整成本"]:
                        note = f"；目前單件完整成本已由 {floor['原完整成本']} 增加為 {floor['新完整成本']}"
                    warn("材料漲價後仍沿用舊價", HIGH,
                         f"供應商調價生效日 {price_increase_date} 之後的報價仍是 {r['報價單價']}，"
                         f"與調價前最近一筆相同{note}",
                         f"{r['報價單號']}/{r['報價行號']}（{r['報價日期'].date()}）＝"
                         f"{prev['報價單號']}/{prev['報價行號']}（{prev['報價日期'].date()}）")

    if not is_blank(proposed_price):
        proposed = parse_number(proposed_price)
        if proposed is None or proposed <= 0:
            warn("擬報價無效", HIGH, f"擬報價「{proposed_price}」不是大於 0 的數字")
        elif floor["可用"] and proposed < floor["安全底價"]:
            warn("擬報價低於安全底線", HIGH,
                 f"擬報價 {proposed} 低於安全底價 {floor['安全底價']}（目標毛利率 {_pct(margin)}）")

    if not floor["可用"]:
        status, message = STATUS_NO_FLOOR, "缺少可驗證的完整成本，無法提供安全底價；請先補齊成本資料"
    elif search.status == INSUFFICIENT:
        status, message = STATUS_INSUFFICIENT, f"安全底價 {floor['安全底價']}；{search.message}"
    elif stats["最低"] < floor["安全底價"]:
        status, message = STATUS_BELOW_FLOOR, (f"安全底價 {floor['安全底價']}；歷史參考區間 {stats['最低']}～{stats['最高']}"
                                              "，其中有低於底線的價格，不得直接沿用舊價")
    else:
        status, message = STATUS_REFERENCE, (f"安全底價 {floor['安全底價']}；歷史參考區間 {stats['最低']}～{stats['最高']}"
                                            "（中位數 " + str(stats["中位數"]) + "），仍需人工核准")
    return Advice(status, message, floor, stats, warnings, missing, evidence,
                  dict(q, 目標毛利率=margin, 供應商調價生效日=price_increase_date, 擬報價=proposed_price))
