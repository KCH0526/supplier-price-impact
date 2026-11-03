"""Auditable per-unit cost impact for a previously validated match result.

All arithmetic uses Decimal; rounding belongs to the presentation/export layer.
Never publish a partial total for a product with a blocking match exception.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

import pandas as pd

from core.matcher import COMPLETE, MatchResult
from core.validation import is_blank, parse_number


IMPACT_COLUMNS = [
    "成品編號", "成品名稱", "試算狀態", "原材料成本", "新材料成本",
    "原成本", "新成本", "成本增加", "成本增加百分比", "原毛利率", "新毛利率",
    "需重算報價", "預估月產量", "預估月成本增加", "成本口徑", "成本資料備註",
]
AUDIT_COLUMNS = [
    "成品編號", "成品名稱", "子件料號", "子件名稱", "單位", "用量", "原單價",
    "試算新單價", "原材料金額", "新材料金額", "單行成本差額", "配對狀態",
    "供應商代碼", "BOM列號", "報價列號", "報價單號", "報價生效日", "成品試算完整",
]
FULL_BASIS = "完整估算：材料＋人工＋製費＋其他"
MATERIAL_BASIS = "僅材料成本（非完整成本）"
NONMATERIAL_COLS = ("單件人工成本", "單件製造費用", "單件其他成本")


@dataclass
class CostResult:
    cost_impact: pd.DataFrame
    line_audit: pd.DataFrame
    summary: dict


def _id(value):
    return None if is_blank(value) else str(value).strip()


def _nonnegative(value) -> Decimal | None:
    number = parse_number(value)
    return number if number is not None and number >= 0 else None


def _positive(value) -> Decimal | None:
    number = parse_number(value)
    return number if number is not None and number > 0 else None


def _cost_data(product_cost: pd.DataFrame | None):
    """Never arbitrarily select one of several cost records for a product."""
    records: dict[str, dict | None] = {}
    if product_cost is None:
        return records
    for row in product_cost.to_dict("records"):
        product = _id(row.get("成品編號"))
        if product is None:
            continue
        if product in records:
            records[product] = None  # Duplicate => ambiguous; do not use it.
        else:
            records[product] = row
    return records


def calculate_cost_impact(matched: MatchResult, product_cost: pd.DataFrame | None = None) -> CostResult:
    """Calculate per-unit costs, valid gross margins, and production-weighted impact.

    `product_cost` is the optional ProductCost worksheet. Missing fixed cost
    fields force a material-only basis; a sale price alone never creates a
    misleading gross margin. Monthly total is omitted if any product lacks a
    valid forecast or is incomplete.
    """
    costs = _cost_data(product_cost)
    audit_rows = []
    by_product: dict[str, list[dict]] = {}
    for item in matched.matched_items.to_dict("records"):
        qty = parse_number(item["用量"])
        old_unit = parse_number(item["原單價"])
        new_unit = parse_number(item["適用單價"])
        # Matcher is responsible for rejecting non-numeric and invalid rows.
        if qty is None or old_unit is None or new_unit is None:
            raise ValueError("matched_items 含無法計算的數字；請先完成資料驗證")
        old_amount, new_amount = qty * old_unit, qty * new_unit
        rec = {
            "成品編號": item["成品編號"], "成品名稱": item["成品名稱"],
            "子件料號": item["子件料號"], "子件名稱": item["子件名稱"],
            "單位": item["單位"], "用量": qty, "原單價": old_unit,
            "試算新單價": new_unit, "原材料金額": old_amount,
            "新材料金額": new_amount, "單行成本差額": new_amount - old_amount,
            "配對狀態": item["配對狀態"], "供應商代碼": item["供應商代碼"],
            "BOM列號": item["BOM列號"], "報價列號": item["報價列號"],
            "報價單號": item["報價單號"], "報價生效日": item["報價生效日"],
            "成品試算完整": item["成品試算完整"],
        }
        audit_rows.append(rec)
        by_product.setdefault(item["成品編號"], []).append(rec)

    impact_rows = []
    for status in matched.product_status.to_dict("records"):
        product = status["成品編號"]
        row = {c: None for c in IMPACT_COLUMNS}
        row.update({"成品編號": product, "成品名稱": status["成品名稱"],
                    "試算狀態": status["狀態"], "需重算報價": "待人工確認",
                    "成本口徑": "不可計算", "成本資料備註": "存在阻擋例外，禁止顯示部分成本"})
        if status["狀態"] != COMPLETE or status["可計算行數"] != status["BOM行數"]:
            impact_rows.append(row)
            continue

        lines = by_product.get(product, [])
        if len(lines) != status["BOM行數"]:
            # Defensive check: a caller cannot silently drop one BOM line.
            impact_rows.append(row)
            continue

        material_old = sum((r["原材料金額"] for r in lines), Decimal(0))
        material_new = sum((r["新材料金額"] for r in lines), Decimal(0))
        metadata = costs.get(product)
        fixed = None
        if metadata is not None and all(col in metadata for col in NONMATERIAL_COLS):
            pieces = [_nonnegative(metadata.get(col)) for col in NONMATERIAL_COLS]
            if all(piece is not None for piece in pieces):
                fixed = sum(pieces, Decimal(0))

        full = fixed is not None
        old_cost = material_old + (fixed if full else Decimal(0))
        new_cost = material_new + (fixed if full else Decimal(0))
        difference = new_cost - old_cost
        row.update({
            "原材料成本": material_old, "新材料成本": material_new,
            "原成本": old_cost, "新成本": new_cost, "成本增加": difference,
            "成本增加百分比": difference / old_cost if old_cost != 0 else None,
            "需重算報價": "是" if difference > 0 else "否",
            "成本口徑": FULL_BASIS if full else MATERIAL_BASIS,
            "成本資料備註": None if full else "人工／製費／其他成本不完整；不可計算真正毛利率",
        })
        if full and metadata is not None and _id(metadata.get("銷售幣別")) == "TWD":
            selling = _positive(metadata.get("未稅銷售單價"))
            if selling is not None:
                row["原毛利率"] = (selling - old_cost) / selling
                row["新毛利率"] = (selling - new_cost) / selling

        if metadata is not None:
            monthly_qty = _nonnegative(metadata.get("預估月產量"))
            if monthly_qty is not None:
                row["預估月產量"] = monthly_qty
                row["預估月成本增加"] = difference * monthly_qty
        impact_rows.append(row)

    complete_rows = [r for r in impact_rows if r["成本增加"] is not None]
    can_sum_month = bool(impact_rows) and all(r["預估月成本增加"] is not None for r in impact_rows)
    winner = max(complete_rows, key=lambda r: r["成本增加"], default=None)
    summary = {
        "總成品數": len(impact_rows),
        "可完整試算成品數": len(complete_rows),
        "未完成成品數": len(impact_rows) - len(complete_rows),
        "受影響成品數": sum(1 for r in complete_rows if r["成本增加"] != 0),
        "預估每月總成本增加": sum((r["預估月成本增加"] for r in impact_rows), Decimal(0)) if can_sum_month else None,
        "最高單件成本增加成品": winner["成品編號"] if winner else None,
        "最高單件成本增加金額": winner["成本增加"] if winner else None,
    }
    return CostResult(
        cost_impact=pd.DataFrame(impact_rows, columns=IMPACT_COLUMNS, dtype=object),
        line_audit=pd.DataFrame(audit_rows, columns=AUDIT_COLUMNS, dtype=object),
        summary=summary,
    )
