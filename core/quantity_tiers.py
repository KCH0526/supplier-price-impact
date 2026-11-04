"""Quantity tiers and minimum price per quantity (PR #23).

Rules: docs/COMMERCIAL_QUOTING_SPEC.md section 4.

    每件情境成本 = 單件變動成本 + 批次固定成本 ÷ 數量
    安全底價（試算） = 每件情境成本 ÷ (1 − 目標毛利率), Decimal, rounded UP to the cent

In the existing-cost mode the batch fixed cost is not modelled and is
stated as such. Changes of material price, yield, labour time or
outsourcing price with quantity are not simulated: without data they are
not guessed.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from decimal import Decimal

import pandas as pd

from core.batch_cost import CostModel
from core.quote_risk import ceil_cent, parse_min_margin
from core.quote_search import search_similar_quotes

MAX_QUANTITIES = 20
STATUS_OK = "可試算"
STATUS_BELOW_MOQ = "低於最低訂購量"
STATUS_NO_COST = "成本不可用"
NOT_SIMULATED = "未模擬數量對原料議價、良率、工時、委外價的影響"
COLUMNS = ["數量", "狀態", "單件變動成本", "批次固定成本", "每件分攤固定費", "每件情境成本", "目標毛利率",
           "安全底價（試算）", "計算式", "歷史筆數", "歷史中位數", "底價與歷史中位數差額", "說明"]


@dataclass
class TierResult:
    rows: pd.DataFrame
    model: CostModel
    margin: Decimal
    notes: list[str] = field(default_factory=list)


def _quantities(values) -> list[int]:
    if not values:
        raise ValueError("請至少輸入一個數量")
    if len(values) > MAX_QUANTITIES:
        raise ValueError(f"一次最多 {MAX_QUANTITIES} 個數量")
    out = []
    for v in values:
        if isinstance(v, bool) or not isinstance(v, (int, float, Decimal, str)):
            raise ValueError(f"數量「{v}」不是有效的正整數")
        try:
            d = Decimal(str(v).strip())
        except Exception as exc:  # noqa: BLE001
            raise ValueError(f"數量「{v}」不是有效的正整數") from exc
        if not d.is_finite() or d <= 0 or d != d.to_integral_value():
            raise ValueError(f"數量「{v}」必須是正整數（pcs）")
        out.append(int(d))
    if len(set(out)) != len(out):
        raise ValueError("數量不可重複")
    return sorted(out)


def compute_quantity_tiers(model: CostModel, quantities, target_margin, moq=None, history_records=None,
                           as_of: dt.date | None = None, drawing_version: str | None = None) -> TierResult:
    qtys = _quantities(quantities)
    margin = parse_min_margin(target_margin)
    moq_value = None if moq in (None, "") else _quantities([moq])[0]
    rows = []
    for q in qtys:
        row = {c: None for c in COLUMNS}
        row.update({"數量": q, "目標毛利率": margin, "單件變動成本": model.unit_variable,
                    "批次固定成本": model.batch_fixed})
        notes = []
        if not model.available:
            row["狀態"] = STATUS_NO_COST
            notes.append("；".join(model.missing) or "成本不可用")
        elif moq_value is not None and q < moq_value:
            row["狀態"] = STATUS_BELOW_MOQ
            notes.append(f"數量 {q} 低於最低訂購量 {moq_value}，不提供底價")
        else:
            row["狀態"] = STATUS_OK
            if model.batch_fixed is None:
                share = None
                cost = model.unit_variable
                notes.append("既有完整成本模式：未計入批次固定費")
                formula = f"{cost:.2f} ÷ (1 − {margin})"
            else:
                share = model.batch_fixed / q
                cost = model.unit_variable + share
                formula = f"({model.unit_variable} + {model.batch_fixed} ÷ {q}) ÷ (1 − {margin})"
            price = ceil_cent(cost / (1 - margin))
            row.update({"每件分攤固定費": share, "每件情境成本": cost, "安全底價（試算）": price,
                        "計算式": f"{formula} = {cost / (1 - margin):.4f}，無條件進位為 {price}"})
            if history_records is not None and as_of is not None:
                search = search_similar_quotes(history_records, model.product, q, as_of, "pcs",
                                               drawing_version=drawing_version)
                if search.stats:
                    row["歷史筆數"] = search.stats["筆數"]
                    row["歷史中位數"] = search.stats["中位數"]
                    row["底價與歷史中位數差額"] = price - search.stats["中位數"]
                else:
                    notes.append(search.message)
        notes.append(NOT_SIMULATED)
        row["說明"] = "；".join(notes)
        rows.append(row)
    return TierResult(pd.DataFrame(rows, columns=COLUMNS, dtype=object), model, margin,
                      [model.basis, NOT_SIMULATED] + model.warnings)
