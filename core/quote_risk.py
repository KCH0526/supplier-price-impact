"""Customer-quote gross-margin risk review.

Takes the validated cost result (core.calculator) and the OpenQuotes sheet,
and for each quote line answers: is the estimated margin after the supplier
price change still at or above the user's floor?

Rules:
- Only quotes with status 有效 and 生效日 <= as_of <= 截止日 are assessed.
- A quote is only assessed when its product has a COMPLETE full cost
  (material + labour + overhead + other). Missing cost is never treated as 0.
- Invalid quotes get no margin figures at all.
- 報價情境成本增加 is a scenario amount based on the quoted quantity. It is
  not a confirmed order, an actual loss, or a legal claim.
- Nothing here changes a quote; every flagged line needs human review.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from decimal import ROUND_CEILING, Decimal, InvalidOperation

import pandas as pd

from core.calculator import FULL_BASIS, CostResult
from core.matcher import COMPLETE
from core.quote_reader import QUOTE_SHEET
from core.quote_validation import QUOTE_ACTIVE, classify_quote_status, validate_open_quotes
from core.validation import ERROR, ROW_COLUMN, WARNING, is_blank, parse_date, parse_number

DEFAULT_MIN_MARGIN = Decimal("0.15")

STATUS_REVIEW = "需人工覆核"
STATUS_OK = "尚符合設定底線"
STATUS_UNRELIABLE = "無法可靠判斷"
STATUS_EXCLUDED = "不納入試算"
_STATUS_RANK = {STATUS_REVIEW: 0, STATUS_UNRELIABLE: 1, STATUS_OK: 2, STATUS_EXCLUDED: 3}

SCENARIO_NOTE = "依報價數量推估的情境金額；不是已確認訂單量、實際損失或可向客戶主張的金額"

RISK_COLUMNS = [
    "風險排序", "覆核狀態", "問題原因", "客戶代碼", "報價單號", "行號", "成品編號",
    "未稅報價單價", "報價數量", "原完整成本", "新完整成本", "原毛利率", "新毛利率",
    "毛利率下降百分點", "報價情境成本增加", "設定毛利率底線", "維持底線所需最低單價",
    "來源Excel列號",
]
QUOTE_EXCEPTION_COLUMNS = [
    "類型", "是否阻擋", "工作表", "Excel列號", "報價單號", "行號", "成品編號", "欄位", "原因",
]
_CENT = Decimal("0.01")


@dataclass
class QuoteRiskResult:
    risk: pd.DataFrame
    exceptions: pd.DataFrame
    summary: dict


def parse_min_margin(value) -> Decimal:
    """Accept 0 <= floor < 1 (e.g. 0.15 for 15%). Anything else raises ValueError."""
    if isinstance(value, float):
        value = repr(value)
    try:
        floor = Decimal(str(value).strip())
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"最低毛利率必須是 0 到 1 之間的數字（例如 0.15），收到：{value!r}") from exc
    if not floor.is_finite() or floor < 0 or floor >= 1:
        raise ValueError(f"最低毛利率必須介於 0（含）與 1（不含）之間，收到：{value!r}")
    return floor


def ceil_cent(value: Decimal) -> Decimal:
    return value.quantize(_CENT, rounding=ROUND_CEILING)


def _pct(value: Decimal) -> str:
    return f"{(value * 100).quantize(_CENT, rounding='ROUND_HALF_UP')}%"


def _text(rec, col):
    value = rec.get(col)
    return None if is_blank(value) else str(value).strip()


def assess_quote_risk(
    quotes: pd.DataFrame,
    costs: CostResult,
    as_of: dt.date,
    min_margin=DEFAULT_MIN_MARGIN,
) -> QuoteRiskResult:
    if not isinstance(as_of, dt.date):
        raise TypeError("as_of 必須是日期")
    if isinstance(as_of, dt.datetime):
        as_of = as_of.date()
    floor = parse_min_margin(min_margin)

    product_costs = {_text(r, "成品編號"): r for r in costs.cost_impact.to_dict("records")}
    issues = validate_open_quotes(quotes)
    errors_by_row: dict[int, list] = {}
    for issue in issues:
        if issue.severity == ERROR:
            errors_by_row.setdefault(issue.row, []).append(issue)

    exceptions = []

    def add_exc(kind, blocking, rec, column, reason):
        exceptions.append({
            "類型": kind, "是否阻擋": blocking, "工作表": QUOTE_SHEET, "Excel列號": rec[ROW_COLUMN],
            "報價單號": _text(rec, "報價單號"), "行號": _text(rec, "行號"), "成品編號": _text(rec, "成品編號"),
            "欄位": column, "原因": reason,
        })

    by_row = {r[ROW_COLUMN]: r for r in quotes.to_dict("records")}
    for issue in issues:
        kind = "報價資料無效" if issue.severity == ERROR else "報價不納入試算"
        add_exc(kind, issue.severity == ERROR, by_row[issue.row], issue.column, issue.reason)

    rows = []
    for rec in quotes.to_dict("records"):
        row_no = rec[ROW_COLUMN]
        out = {c: None for c in RISK_COLUMNS}
        out.update({
            "客戶代碼": _text(rec, "客戶代碼"), "報價單號": _text(rec, "報價單號"), "行號": _text(rec, "行號"),
            "成品編號": _text(rec, "成品編號"), "未稅報價單價": parse_number(rec.get("未稅報價單價")),
            "報價數量": parse_number(rec.get("報價數量")), "設定毛利率底線": floor, "來源Excel列號": row_no,
        })
        rows.append(out)

        if row_no in errors_by_row:
            out["覆核狀態"] = STATUS_UNRELIABLE
            out["問題原因"] = "報價資料無效：" + "；".join(i.reason for i in errors_by_row[row_no])
            continue
        if classify_quote_status(rec.get("報價狀態")) != QUOTE_ACTIVE:
            out["覆核狀態"] = STATUS_EXCLUDED
            out["問題原因"] = f"報價狀態為「{_text(rec, '報價狀態')}」，不納入試算"
            continue
        start, end = parse_date(rec["生效日"]), parse_date(rec["截止日"])
        if start > as_of:
            out["覆核狀態"] = STATUS_EXCLUDED
            out["問題原因"] = f"報價尚未生效（生效日 {start} 晚於試算基準日 {as_of}）"
            add_exc("報價尚未生效", False, rec, "生效日", out["問題原因"])
            continue
        if end < as_of:
            out["覆核狀態"] = STATUS_EXCLUDED
            out["問題原因"] = f"報價已過期（截止日 {end} 早於試算基準日 {as_of}）"
            add_exc("報價已過期", False, rec, "截止日", out["問題原因"])
            continue

        product = out["成品編號"]
        cost = product_costs.get(product)
        problem = None
        if cost is None:
            problem = ("成品不存在於 BOM", f"成品「{product}」不在本次 BOM 試算結果中，無法取得成本")
        elif cost["試算狀態"] != COMPLETE or cost["原成本"] is None or cost["新成本"] is None:
            problem = ("成品成本不完整", f"成品「{product}」有阻擋例外，成本不完整；不會以 0 或部分成本計算毛利")
        elif cost["成本口徑"] != FULL_BASIS:
            problem = ("缺少完整成本", f"成品「{product}」缺少人工、製造費用或其他成本，只有材料成本，無法計算完整毛利率")
        if problem:
            out["覆核狀態"] = STATUS_UNRELIABLE
            out["問題原因"] = problem[1]
            add_exc(problem[0], True, rec, "成品編號", problem[1])
            continue

        price, qty = out["未稅報價單價"], out["報價數量"]
        old_cost, new_cost = Decimal(cost["原成本"]), Decimal(cost["新成本"])
        old_margin = (price - old_cost) / price
        new_margin = (price - new_cost) / price
        out.update({
            "原完整成本": old_cost, "新完整成本": new_cost, "原毛利率": old_margin, "新毛利率": new_margin,
            "毛利率下降百分點": (old_margin - new_margin) * 100,
            "報價情境成本增加": (new_cost - old_cost) * qty,
            "維持底線所需最低單價": ceil_cent(new_cost / (1 - floor)),
        })
        change = new_cost - old_cost
        if change > 0:
            cost_note = f"單件成本增加 {change.quantize(_CENT)}（{SCENARIO_NOTE}：{out['報價情境成本增加'].quantize(_CENT)}）"
        elif change < 0:
            cost_note = f"成本下降，單件減少 {(-change).quantize(_CENT)}"
        else:
            cost_note = "成本未變動"
        if new_margin < floor:
            out["覆核狀態"] = STATUS_REVIEW
            when = "調價前已低於底線" if old_margin < floor else "漲價後才低於底線"
            out["問題原因"] = (f"新毛利率 {_pct(new_margin)} 低於設定底線 {_pct(floor)}（{when}）；"
                            f"維持底線需至少 {out['維持底線所需最低單價']}；{cost_note}")
        else:
            out["覆核狀態"] = STATUS_OK
            out["問題原因"] = f"新毛利率 {_pct(new_margin)}，不低於底線 {_pct(floor)}；{cost_note}"

    def risk_key(r):
        gap = (r["新毛利率"] - floor) if r["新毛利率"] is not None else Decimal(0)
        scenario = r["報價情境成本增加"] or Decimal(0)
        return (_STATUS_RANK[r["覆核狀態"]], gap, -scenario, r["來源Excel列號"])

    rows.sort(key=risk_key)
    for i, r in enumerate(rows, 1):
        r["風險排序"] = i

    assessed = [r for r in rows if r["報價情境成本增加"] is not None]
    review = [r for r in assessed if r["覆核狀態"] == STATUS_REVIEW]
    summary = {status: sum(1 for r in rows if r["覆核狀態"] == status) for status in _STATUS_RANK}
    summary.update({
        "報價總列數": len(rows),
        "設定毛利率底線": floor,
        "試算基準日": as_of,
        "報價情境成本增加合計": sum((r["報價情境成本增加"] for r in assessed), Decimal(0)),
        "需人工覆核報價情境成本增加合計": sum((r["報價情境成本增加"] for r in review), Decimal(0)),
        "情境金額說明": SCENARIO_NOTE,
    })
    return QuoteRiskResult(
        risk=pd.DataFrame(rows, columns=RISK_COLUMNS, dtype=object),
        exceptions=pd.DataFrame(exceptions, columns=QUOTE_EXCEPTION_COLUMNS, dtype=object),
        summary=summary,
    )
