"""Match supplier price quotes to BOM lines and detect business exceptions.

Input: the DataFrames returned by ``core.reader`` and an explicit as-of date.
No cost totals are calculated here; the output is the per-line audit data the
cost step needs, plus exceptions and a per-product completeness status.

Safety rules (docs/IMPLEMENTATION_SPEC.md §3):
- A quote is applicable only when 生效日 <= as_of <= 價格迄日 (if given) and,
  when 報價狀態 is present, it is 核准.
- No currency, unit, base-quantity or price-quantity conversion is done;
  anything other than the supported value blocks the line.
- An existing but unusable quote is never treated as "no price change".
- A product with any blocking exception is marked incomplete; its other
  lines are still listed for audit but flagged 成品試算完整 = False.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal

import pandas as pd

from core.validation import (
    BOM_SHEET,
    ERROR,
    PRICE_SHEET,
    ROW_COLUMN,
    is_blank,
    parse_date,
    parse_number,
    validate_bom,
    validate_price_increase,
)

COMPLETE = "可完整試算"
INCOMPLETE = "試算不完整／需人工確認"
STATUS_ADJUSTED = "已調價"
STATUS_UNCHANGED = "未調價沿用原價"

SUPPORTED_CURRENCY = "TWD"
APPROVED_QUOTE = "核准"
APPROVED_BOM = "已核准"
PURCHASED_PART = "採購件"
EXPLODED_YES = "是"

EXCEPTION_COLUMNS = ["類型", "是否阻擋", "工作表", "Excel列號", "子件料號", "供應商代碼", "原因", "影響成品"]
MATCHED_COLUMNS = [
    "BOM列號", "成品編號", "成品名稱", "子件料號", "子件名稱", "工廠代碼", "供應商代碼", "單位", "用量",
    "原單價", "適用單價", "單價差額", "配對狀態", "報價列號", "報價單號", "報價生效日", "成品試算完整",
]
STATUS_COLUMNS = ["成品編號", "成品名稱", "狀態", "BOM行數", "可計算行數", "阻擋例外數", "阻擋料號"]


@dataclass
class MatchResult:
    matched_items: pd.DataFrame
    exceptions: pd.DataFrame
    product_status: pd.DataFrame


class _Exceptions:
    """Collects exceptions, merging the products affected by the same problem."""

    def __init__(self):
        self._items: dict[tuple, dict] = {}

    def add(self, kind, sheet, row, item, supplier, reason, *, blocking, product=None):
        key = (kind, sheet, row, reason)
        rec = self._items.setdefault(key, {
            "類型": kind, "是否阻擋": blocking, "工作表": sheet, "Excel列號": row,
            "子件料號": item, "供應商代碼": supplier, "原因": reason, "_products": set(),
        })
        if product is not None:
            rec["_products"].add(product)

    def frame(self) -> pd.DataFrame:
        rows = []
        for rec in self._items.values():
            rec = dict(rec)
            rec["影響成品"] = ", ".join(sorted(rec.pop("_products")))
            rows.append(rec)
        rows.sort(key=lambda r: (r["工作表"] != BOM_SHEET, r["Excel列號"] or 0, r["類型"]))
        return pd.DataFrame(rows, columns=EXCEPTION_COLUMNS, dtype=object)


def _text(rec, column):
    value = rec.get(column)
    return None if is_blank(value) else str(value).strip()


def _differs(a, b):
    """Both values present and different. A missing value is not a conflict."""
    return a is not None and b is not None and a != b


def _error_reasons(issues) -> dict[int, list[str]]:
    out: dict[int, list[str]] = {}
    for issue in issues:
        if issue.severity == ERROR and issue.row is not None:
            out.setdefault(issue.row, []).append(issue.reason)
    return out


def _bom_line_problems(rec, bad_reasons):
    """Blocking problems that come from the BOM line itself."""
    problems = [("BOM 資料無效", r) for r in bad_reasons]
    status = _text(rec, "BOM狀態") if "BOM狀態" in rec else APPROVED_BOM
    if status != APPROVED_BOM:
        problems.append(("BOM 未核准", f"BOM狀態為「{status or '空白'}」，只接受「{APPROVED_BOM}」"))
    if "BOM基準產量" in rec and not is_blank(rec["BOM基準產量"]) and parse_number(rec["BOM基準產量"]) != 1:
        problems.append(("BOM 基準產量不支援", f"BOM基準產量為 {rec['BOM基準產量']}，MVP 只接受 1"))
    part_type = _text(rec, "子件類型")
    exploded = _text(rec, "已展開至最底層")
    if ("子件類型" in rec and part_type != PURCHASED_PART) or ("已展開至最底層" in rec and exploded != EXPLODED_YES):
        problems.append((
            "未展開半成品",
            f"子件類型「{part_type or '空白'}」、已展開至最底層「{exploded or '空白'}」；只接受已展開的採購件",
        ))
    if "原單價幣別" in rec and _text(rec, "原單價幣別") != SUPPORTED_CURRENCY:
        problems.append(("幣別不一致", f"原單價幣別為「{_text(rec, '原單價幣別') or '空白'}」，MVP 只接受 {SUPPORTED_CURRENCY}"))
    if "原單價計價數量" in rec and not is_blank(rec["原單價計價數量"]) and parse_number(rec["原單價計價數量"]) != 1:
        problems.append(("計價數量不支援", f"原單價計價數量為 {rec['原單價計價數量']}，MVP 只接受 1，不自動換算"))
    return problems


def match_prices(bom: pd.DataFrame, price: pd.DataFrame, as_of: dt.date) -> MatchResult:
    if not isinstance(as_of, dt.date):
        raise TypeError("as_of 必須是日期")
    if isinstance(as_of, dt.datetime):
        as_of = as_of.date()

    exc = _Exceptions()
    bad_bom = _error_reasons(validate_bom(bom))
    bad_price = _error_reasons(validate_price_increase(price))
    bom_records = bom.to_dict("records")
    bom_items = {_text(r, "子件料號") for r in bom_records} - {None}

    # ---- classify every quote row ----
    usable: dict[str, list[dict]] = {}      # item -> applicable, approved, valid quotes
    item_blocks: dict[str, list[tuple]] = {}  # item -> blocking price-row problems
    item_notes: dict[str, list[tuple]] = {}   # item -> non-blocking price-row notes
    for q in price.to_dict("records"):
        row, item, supplier = q[ROW_COLUMN], _text(q, "子件料號"), _text(q, "供應商代碼")
        in_bom = item in bom_items
        if not in_bom:
            exc.add("漲價料號未匹配", PRICE_SHEET, row, item, supplier,
                    "報價料號不在本次 BOM，不套用到任何成品", blocking=False)
        if row in bad_price:
            for reason in bad_price[row]:
                if in_bom:
                    item_blocks.setdefault(item, []).append(("報價資料無效", row, supplier, reason))
                else:
                    exc.add("報價資料無效", PRICE_SHEET, row, item, supplier, reason, blocking=False)
            continue
        if not in_bom:
            continue
        start, end = parse_date(q["生效日"]), parse_date(q.get("價格迄日"))
        if start > as_of:
            item_notes.setdefault(item, []).append(
                ("報價尚未生效", row, supplier, f"生效日 {start} 晚於試算基準日 {as_of}，不套價，沿用原價"))
            continue
        if end is not None and end < as_of:
            item_notes.setdefault(item, []).append(
                ("報價已過期", row, supplier, f"價格迄日 {end} 早於試算基準日 {as_of}，不套價，沿用原價"))
            continue
        if "報價狀態" in q and _text(q, "報價狀態") != APPROVED_QUOTE:
            item_blocks.setdefault(item, []).append((
                "報價未核准", row, supplier,
                f"報價狀態為「{_text(q, '報價狀態') or '空白'}」，只接受「{APPROVED_QUOTE}」"))
            continue
        usable.setdefault(item, []).append(q)

    # ---- evaluate every BOM line ----
    lines = []
    for b in bom_records:
        row, product, item = b[ROW_COLUMN], _text(b, "成品編號"), _text(b, "子件料號")
        b_supplier, b_plant, b_unit = _text(b, "供應商代碼"), _text(b, "工廠代碼"), _text(b, "單位")
        b_currency = _text(b, "原單價幣別") or SUPPORTED_CURRENCY
        blocked = False

        for kind, reason in _bom_line_problems(b, bad_bom.get(row, [])):
            exc.add(kind, BOM_SHEET, row, item, b_supplier, reason, blocking=True, product=product)
            blocked = True

        for kind, q_row, q_supplier, reason in item_blocks.get(item, []):
            exc.add(kind, PRICE_SHEET, q_row, item, q_supplier, reason, blocking=True, product=product)
            blocked = True
        for kind, q_row, q_supplier, reason in item_notes.get(item, []):
            exc.add(kind, PRICE_SHEET, q_row, item, q_supplier, reason, blocking=False, product=product)

        quotes = usable.get(item, [])
        problems = []  # (kind, quote, reason)
        wrong_plant = [q for q in quotes if _differs(_text(q, "工廠代碼"), b_plant)]
        problems += [("工廠不符", q, f"報價工廠「{_text(q, '工廠代碼')}」與 BOM 工廠「{b_plant}」不同")
                     for q in wrong_plant]
        quotes = [q for q in quotes if q not in wrong_plant]

        suppliers = {_text(q, "供應商代碼") for q in quotes} - {None}
        if len(suppliers) > 1:
            problems += [("一料多供應商", q, f"同一料號有多家供應商有效報價（{', '.join(sorted(suppliers))}），不可任選其一")
                         for q in quotes]
        elif any(_differs(_text(q, "供應商代碼"), b_supplier) for q in quotes):
            problems += [("供應商不符", q, f"報價供應商「{_text(q, '供應商代碼')}」與 BOM 供應商「{b_supplier}」不同")
                         for q in quotes]
        elif len(quotes) > 1:
            rows = ", ".join(str(q[ROW_COLUMN]) for q in quotes)
            problems += [("重複報價", q, f"同一料號、工廠、供應商在試算日有多筆有效報價（列 {rows}），不可任選其一")
                         for q in quotes]
        elif len(quotes) == 1:
            q = quotes[0]
            if _text(q, "單位") != b_unit:
                problems.append(("單位不一致", q, f"報價單位「{_text(q, '單位')}」與 BOM 單位「{b_unit}」不同，不自動換算"))
            if _text(q, "幣別") != b_currency:
                problems.append(("幣別不一致", q, f"報價幣別「{_text(q, '幣別')}」與 BOM 幣別「{b_currency}」不同，不自動換匯"))
            if "計價數量" in q and not is_blank(q["計價數量"]) and parse_number(q["計價數量"]) != 1:
                problems.append(("計價數量不支援", q, f"報價計價數量為 {q['計價數量']}，MVP 只接受 1，不自動換算"))

        for kind, q, reason in problems:
            exc.add(kind, PRICE_SHEET, q[ROW_COLUMN], item, _text(q, "供應商代碼"), reason,
                    blocking=True, product=product)
            blocked = True

        if blocked:
            lines.append({"_product": product, "_name": b.get("成品名稱"), "_item": item, "_ok": False})
            continue

        old = parse_number(b["原單價"])
        quote = quotes[0] if quotes else None
        new = parse_number(quote["新單價"]) if quote else old
        lines.append({
            "_product": product, "_name": b.get("成品名稱"), "_item": item, "_ok": True,
            "BOM列號": row, "成品編號": product, "成品名稱": b.get("成品名稱"), "子件料號": item,
            "子件名稱": b.get("子件名稱"), "工廠代碼": b_plant, "供應商代碼": b_supplier, "單位": b_unit,
            "用量": parse_number(b["用量"]), "原單價": old, "適用單價": new, "單價差額": new - old,
            "配對狀態": STATUS_ADJUSTED if quote else STATUS_UNCHANGED,
            "報價列號": quote[ROW_COLUMN] if quote else None,
            "報價單號": _text(quote, "報價單號") if quote else None,
            "報價生效日": parse_date(quote["生效日"]) if quote else None,
        })

    exceptions = exc.frame()

    # ---- product status ----
    blocked_items: dict[str, set] = {}
    blocking_count: dict[str, int] = {}
    for rec in exceptions.to_dict("records"):
        if rec["是否阻擋"]:
            for p in filter(None, rec["影響成品"].split(", ")):
                blocked_items.setdefault(p, set()).add(rec["子件料號"])
                blocking_count[p] = blocking_count.get(p, 0) + 1

    status_rows, seen = [], {}
    for line in lines:
        p = line["_product"]
        if p not in seen:
            seen[p] = {"成品編號": p, "成品名稱": line["_name"], "BOM行數": 0, "可計算行數": 0}
            status_rows.append(seen[p])
        seen[p]["BOM行數"] += 1
        seen[p]["可計算行數"] += int(line["_ok"])
    for s in status_rows:
        p = s["成品編號"]
        s["狀態"] = INCOMPLETE if p in blocked_items else COMPLETE
        s["阻擋例外數"] = blocking_count.get(p, 0)
        s["阻擋料號"] = ", ".join(sorted(i for i in blocked_items.get(p, set()) if i))

    complete = {s["成品編號"] for s in status_rows if s["狀態"] == COMPLETE}
    matched = [
        {**{k: v for k, v in line.items() if not k.startswith("_")}, "成品試算完整": line["_product"] in complete}
        for line in lines if line["_ok"]
    ]
    return MatchResult(
        matched_items=pd.DataFrame(matched, columns=MATCHED_COLUMNS, dtype=object),
        exceptions=exceptions,
        product_status=pd.DataFrame(status_rows, columns=STATUS_COLUMNS, dtype=object),
    )
