"""Customer-facing quote draft built from an allow-list (PR #21).

Rules: docs/COMMERCIAL_QUOTING_SPEC.md section 2.

The draft is assembled from scratch: only fields named in ALLOWED_HEADER /
ALLOWED_LINE are copied; anything else passed in is ignored. The builder
takes no cost, advice or historical object, so it cannot fill in a price
by itself. Prices are typed by a person; a blank price keeps the draft
"未核准草稿". The system never sends, signs or approves anything.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from io import BytesIO

import openpyxl
from openpyxl.styles import Font, PatternFill

from core.report import _safe_value
from core.validation import is_blank, parse_number

ALLOWED_HEADER = ["客戶代碼", "客戶名稱", "報價單號", "報價版本", "報價日期", "報價有效期限", "交易條件"]
ALLOWED_LINE = ["成品編號", "成品名稱", "規格圖面版次", "數量", "計價單位", "幣別", "報價單價", "交期"]
LABEL_UNAPPROVED = "未核准草稿"
LABEL_CONFIRMED = "報價草稿（價格已人工填寫，本系統不提供核准或簽名）"
SHEET = "報價草稿"
_CENT = Decimal("0.01")


@dataclass
class CustomerDraft:
    header: dict
    lines: list[dict]
    label: str
    total: Decimal | None


def _text(value):
    return None if is_blank(value) else str(value).strip()


def build_customer_draft(header: dict, lines: list[dict], prices_confirmed: bool) -> CustomerDraft:
    """Raises ValueError for anything that cannot be a valid draft."""
    head = {k: header.get(k) for k in ALLOWED_HEADER}
    for k in ("客戶代碼", "客戶名稱", "報價單號", "報價版本", "交易條件"):
        head[k] = _text(head[k])
    if head["客戶代碼"] is None:
        raise ValueError("客戶草稿必須指定一位客戶（客戶代碼）")
    if not lines:
        raise ValueError("客戶草稿至少需要一行明細")

    out, currencies, all_priced = [], set(), True
    for n, raw in enumerate(lines, 1):
        line = {k: raw.get(k) for k in ALLOWED_LINE}
        for k in ("成品編號", "成品名稱", "規格圖面版次", "計價單位", "幣別", "交期"):
            line[k] = _text(line[k])
        if line["成品編號"] is None or line["計價單位"] is None or line["幣別"] is None:
            raise ValueError(f"第 {n} 行：成品編號、計價單位、幣別都必須填寫")
        qty = parse_number(line["數量"])
        if qty is None or qty <= 0:
            raise ValueError(f"第 {n} 行：數量必須是大於 0 的數字")
        line["數量"] = qty
        currencies.add(line["幣別"])
        if is_blank(line["報價單價"]):
            line["報價單價"], line["合計金額"] = None, None
            all_priced = False
        else:
            price = parse_number(line["報價單價"])
            if price is None or price <= 0:
                raise ValueError(f"第 {n} 行：報價單價必須是大於 0 的數字（或留空）")
            line["報價單價"] = price
            line["合計金額"] = (qty * price).quantize(_CENT, rounding=ROUND_HALF_UP)
        out.append(line)
    if len(currencies) > 1:
        raise ValueError(f"一份客戶草稿只能有一種幣別（目前有 {'、'.join(sorted(currencies))}）")

    label = LABEL_CONFIRMED if prices_confirmed and all_priced else LABEL_UNAPPROVED
    total = sum((l["合計金額"] for l in out), Decimal(0)) if all_priced else None
    return CustomerDraft(head, out, label, total)


def _cell(value):
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dt.datetime):
        return value.date().isoformat()
    if isinstance(value, dt.date):
        return value.isoformat()
    return _safe_value(value)


def build_customer_draft_workbook(draft: CustomerDraft) -> bytes:
    """One visible sheet, no hidden sheets, no defined names, no formulas."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = SHEET
    ws.append([draft.label])
    ws["A1"].font = Font(bold=True, size=14, color="9C0006" if draft.label == LABEL_UNAPPROVED else "124559")
    ws.append([])
    for key in ALLOWED_HEADER:
        ws.append([key, _cell(draft.header[key])])
        ws.cell(ws.max_row, 1).font = Font(bold=True)
    ws.append([])
    columns = [*ALLOWED_LINE, "合計金額"]
    ws.append(columns)
    for cell in ws[ws.max_row]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="124559")
    for line in draft.lines:
        ws.append([_cell(line.get(c)) for c in columns])
        for i, c in enumerate(columns, 1):
            if c in ("報價單價", "合計金額") and line.get(c) is not None:
                ws.cell(ws.max_row, i).number_format = "#,##0.00"
            elif c in ("成品編號", "規格圖面版次"):
                ws.cell(ws.max_row, i).number_format = "@"
    ws.append(["合計", None, None, None, None, None, None, None, _cell(draft.total)])
    ws.append([])
    ws.append(["本文件為報價草稿，內容以雙方書面確認為準。"])
    for i, width in enumerate((16, 24, 14, 10, 10, 8, 14, 12, 16), 1):
        ws.column_dimensions[openpyxl.utils.get_column_letter(i)].width = width
    out = BytesIO()
    wb.save(out)
    return out.getvalue()
