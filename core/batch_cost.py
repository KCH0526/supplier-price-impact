"""Batch cost model (PR #22). Rules: docs/COMMERCIAL_QUOTING_SPEC.md section 3.

Two mutually exclusive modes, chosen explicitly per product:

- MODE_EXISTING: the existing COMPLETE full unit cost from core.calculator.
  Batch fees are NOT added, because the existing overhead may already
  contain them and that cannot be proven otherwise.
- MODE_DETAILED: confirmed per-piece variable costs + per-batch fixed costs
  from a BatchCost sheet. ProductCost is not used. Every cost field is
  required: blank means unknown and blocks; 0 must be typed explicitly.

No split of an existing cost into material / labour / overhead is guessed,
and old quotes are never used as costs.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from decimal import Decimal

from core.calculator import FULL_BASIS, CostResult
from core.field_mapper import TARGETS, read_source, standardize, validate_mapping
from core.matcher import COMPLETE
from core.reader import Source, read_sheet
from core.validation import ERROR, ROW_COLUMN, Issue, is_blank, parse_date, parse_number

BATCH_SHEET = "BatchCost"
BATCH_REQUIRED = TARGETS[BATCH_SHEET].required
VARIABLE_COLUMNS = ["單件材料變動成本", "單件人工變動成本", "單件製造費用", "單件委外加工費"]
FIXED_COLUMNS = ["每批開機設定費", "每批換線治具費", "其他批次固定費"]
MODE_EXISTING = "既有完整單件成本"
MODE_DETAILED = "明細批次成本"
CONFIRMED = "已確認"
CURRENCY, UNIT = "TWD", "pcs"
OLD_BASE_DAYS = 365


@dataclass
class BatchCostRecord:
    product: str
    version: str | None
    base_date: dt.date
    components: dict
    source: str
    row: int


@dataclass
class BatchCostTable:
    records: dict = field(default_factory=dict)      # (product, version or "") -> BatchCostRecord
    blocked: dict = field(default_factory=dict)      # (product, version or "") -> reason
    issues: list[Issue] = field(default_factory=list)


@dataclass
class CostModel:
    product: str
    mode: str
    available: bool
    unit_variable: Decimal | None = None
    batch_fixed: Decimal | None = None               # None in MODE_EXISTING: not modelled
    components: dict = field(default_factory=dict)
    basis: str = ""
    source: str = ""
    missing: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _text(v):
    return None if is_blank(v) else str(v).strip()


def read_batch_costs(source: Source, sheet: str = BATCH_SHEET, columns: dict | None = None) -> BatchCostTable:
    table = BatchCostTable()
    if columns is not None:
        src = read_source(source, sheet)
        if src.data is None:
            table.issues = src.issues
            return table
        problems = [i for i in validate_mapping(BATCH_SHEET, columns, src.headers) if i.severity == ERROR]
        if problems:
            table.issues = problems
            return table
        df, table.issues = standardize(BATCH_SHEET, src.data, columns)
        rows = [dict(r, **{ROW_COLUMN: r["來源Excel列號"]}) for r in df.to_dict("records")]
    else:
        result = read_sheet(source, sheet, BATCH_REQUIRED)
        if result.data is None:
            table.issues = result.issues
            return table
        rows = result.data.to_dict("records")

    valid: dict[tuple, list[BatchCostRecord]] = {}
    for r in rows:
        row, errors = r[ROW_COLUMN], []

        def err(col, reason, value=None):
            errors.append(Issue(BATCH_SHEET, row, col, reason, ERROR, value))

        product = _text(r.get("成品編號"))
        if product is None:
            err("成品編號", "「成品編號」不可空白")
        base = parse_date(r.get("成本基準日"))
        if base is None:
            err("成本基準日", "「成本基準日」必須是有效日期", r.get("成本基準日"))
        if _text(r.get("幣別")) != CURRENCY:
            err("幣別", f"幣別「{_text(r.get('幣別')) or '空白'}」；只接受 {CURRENCY}，不換匯", r.get("幣別"))
        if _text(r.get("單位")) != UNIT:
            err("單位", f"單位「{_text(r.get('單位')) or '空白'}」；成本以每件（{UNIT}）計算，不做換算", r.get("單位"))
        if _text(r.get("成本完整性狀態")) != CONFIRMED:
            err("成本完整性狀態", f"成本完整性狀態為「{_text(r.get('成本完整性狀態')) or '空白'}」；只有「{CONFIRMED}」可以計算")
        if _text(r.get("成本來源")) is None:
            err("成本來源", "「成本來源」不可空白")
        components = {}
        for col in VARIABLE_COLUMNS + FIXED_COLUMNS:
            raw = r.get(col)
            if is_blank(raw):
                err(col, f"「{col}」空白代表未知，不可當作 0；若確實為 0 請明確填 0")
                continue
            number = parse_number(raw)
            if number is None or number < 0:
                err(col, f"「{col}」必須是 0 以上的數字", raw)
            else:
                components[col] = number
        table.issues += errors
        if not errors:
            version = _text(r.get("規格圖面版次"))
            rec = BatchCostRecord(product, version, base, components, _text(r.get("成本來源")), row)
            valid.setdefault((product, version or ""), []).append(rec)

    for key, recs in valid.items():
        if len(recs) == 1:
            table.records[key] = recs[0]
        else:
            rows_ = "、".join(str(x.row) for x in recs)
            table.blocked[key] = f"成品「{key[0]}」版次「{key[1] or '空白'}」有 {len(recs)} 筆批次成本（第 {rows_} 列），不任選其一"
            for x in recs:
                table.issues.append(Issue(BATCH_SHEET, x.row, "成品編號", table.blocked[key] + "：重複，全部阻擋", ERROR))
    return table


def cost_model_for(product: str, mode: str, as_of: dt.date, costs: CostResult | None = None,
                   batch: BatchCostTable | None = None, version: str | None = None) -> CostModel:
    if mode not in (MODE_EXISTING, MODE_DETAILED):
        raise ValueError(f"成本模式只能是「{MODE_EXISTING}」或「{MODE_DETAILED}」，不可混用")
    if isinstance(as_of, dt.datetime):
        as_of = as_of.date()
    model = CostModel(product, mode, False)

    if mode == MODE_EXISTING:
        rows = {r["成品編號"]: r for r in costs.cost_impact.to_dict("records")} if costs is not None else {}
        row = rows.get(product)
        if costs is None:
            model.missing.append("尚未提供 BOM 與供應商調價資料")
        elif row is None:
            model.missing.append(f"成品「{product}」不在目前的 BOM 試算結果中")
        elif row["試算狀態"] != COMPLETE or row["新成本"] is None:
            model.missing.append(f"成品「{product}」有阻擋例外，成本不完整")
        elif row["成本口徑"] != FULL_BASIS:
            model.missing.append(f"成品「{product}」缺少人工、製造費用或其他成本，只有材料成本")
        else:
            model.available = True
            model.unit_variable = Decimal(row["新成本"])
            model.basis = "既有完整單件成本（材料＋人工＋製費＋其他）；未計入批次固定費（無法證明既有成本未包含，避免重複計算）"
            model.source = "BOM／供應商調價／ProductCost 試算結果"
        return model

    if batch is None:
        model.missing.append("尚未提供批次成本（BatchCost）資料")
        return model
    key = (product, version or "")
    if key in batch.blocked:
        model.missing.append(batch.blocked[key])
        return model
    rec = batch.records.get(key)
    if rec is None:
        others = sorted(v or "空白" for (p, v) in batch.records if p == product)
        hint = f"；資料中有的版次：{'、'.join(others)}" if others else ""
        model.missing.append(f"沒有成品「{product}」版次「{version or '空白'}」的有效批次成本{hint}")
        return model
    if rec.base_date > as_of:
        model.missing.append(f"成本基準日 {rec.base_date} 晚於試算日 {as_of}")
        return model
    if (as_of - rec.base_date).days > OLD_BASE_DAYS:
        model.warnings.append(f"成本基準日 {rec.base_date} 早於試算日超過 {OLD_BASE_DAYS} 天，請確認成本是否仍適用")
    model.available = True
    model.components = dict(rec.components)
    model.unit_variable = sum((rec.components[c] for c in VARIABLE_COLUMNS), Decimal(0))
    model.batch_fixed = sum((rec.components[c] for c in FIXED_COLUMNS), Decimal(0))
    model.basis = "明細批次成本：單件（材料＋人工＋製費＋委外）＋每批（開機＋換線治具＋其他）÷ 數量；不使用 ProductCost"
    model.source = f"{rec.source}（BatchCost 第 {rec.row} 列）"
    return model
