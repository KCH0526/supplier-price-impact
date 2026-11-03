"""Row-level validation of the OpenQuotes worksheet.

Blocking (ERROR) problems mean the quote line must not get a margin figure.
Cancelled / void quotes are not errors: they are excluded with a WARNING
that records the reason. A blank or unrecognised status is never assumed
to be active. Date windows against the as-of date are checked later by the
risk step, because they depend on the user's chosen date.
"""

from __future__ import annotations

import pandas as pd

from core.quote_reader import QUOTE_SHEET
from core.validation import (
    ERROR,
    ROW_COLUMN,
    WARNING,
    Issue,
    is_blank,
    parse_date,
    parse_number,
)

QUOTE_ACTIVE = "active"
QUOTE_INACTIVE = "inactive"
QUOTE_UNKNOWN = "unknown"

ACTIVE_STATUSES = {"有效"}
INACTIVE_STATUSES = {"已取消", "取消", "失效", "已失效", "作廢", "已作廢"}
SUPPORTED_CURRENCY = "TWD"


def classify_quote_status(value) -> str:
    if is_blank(value):
        return QUOTE_UNKNOWN
    text = str(value).strip()
    if text in ACTIVE_STATUSES:
        return QUOTE_ACTIVE
    if text in INACTIVE_STATUSES:
        return QUOTE_INACTIVE
    return QUOTE_UNKNOWN


def _issue(row, column, reason, severity=ERROR, value=None):
    return Issue(QUOTE_SHEET, row, column, reason, severity, value)


def validate_open_quotes(df: pd.DataFrame) -> list[Issue]:
    issues: list[Issue] = []
    first_row_of_key: dict[tuple, int] = {}
    duplicate_rows: dict[tuple, list[int]] = {}

    for rec in df.to_dict("records"):
        row = rec[ROW_COLUMN]
        for col in ("報價單號", "行號", "成品編號", "客戶代碼"):
            if is_blank(rec.get(col)):
                issues.append(_issue(row, col, f"「{col}」不可空白"))

        price = rec.get("未稅報價單價")
        number = parse_number(price)
        if is_blank(price):
            issues.append(_issue(row, "未稅報價單價", "「未稅報價單價」不可空白", value=price))
        elif number is None or number <= 0:
            issues.append(_issue(row, "未稅報價單價", "「未稅報價單價」必須是大於 0 的有效數字", value=price))

        currency = rec.get("報價幣別")
        if currency != SUPPORTED_CURRENCY:
            issues.append(_issue(row, "報價幣別",
                                 f"報價幣別為「{currency if not is_blank(currency) else '空白'}」；"
                                 f"MVP 只支援 {SUPPORTED_CURRENCY}，不自動換匯", value=currency))

        qty = rec.get("報價數量")
        qty_number = parse_number(qty)
        if is_blank(qty):
            issues.append(_issue(row, "報價數量", "「報價數量」不可空白（空白不視為 0）", value=qty))
        elif qty_number is None or qty_number <= 0:
            issues.append(_issue(row, "報價數量", "「報價數量」必須是大於 0 的有效數字", value=qty))
        elif qty_number != qty_number.to_integral_value():
            issues.append(_issue(row, "報價數量", "成品以 pcs（每件）計價，報價數量須為整數", value=qty))

        start, end = rec.get("生效日"), rec.get("截止日")
        start_d, end_d = parse_date(start), parse_date(end)
        for col, raw, parsed in (("生效日", start, start_d), ("截止日", end, end_d)):
            if is_blank(raw):
                issues.append(_issue(row, col, f"「{col}」不可空白"))
            elif parsed is None:
                issues.append(_issue(row, col, f"「{col}」不是有效日期（只接受 Excel 日期或 YYYY-MM-DD）", value=raw))
        if start_d and end_d and start_d > end_d:
            issues.append(_issue(row, "截止日", f"生效日 {start_d} 晚於截止日 {end_d}", value=end))

        status = rec.get("報價狀態")
        kind = classify_quote_status(status)
        if kind == QUOTE_INACTIVE:
            issues.append(_issue(row, "報價狀態", f"報價狀態為「{str(status).strip()}」，不納入試算",
                                 WARNING, status))
        elif kind == QUOTE_UNKNOWN:
            shown = "空白" if is_blank(status) else str(status).strip()
            issues.append(_issue(row, "報價狀態",
                                 f"報價狀態「{shown}」無法辨識；只有「有效」會納入試算，不會自行假設為有效",
                                 value=status))

        quote_no, line = rec.get("報價單號"), rec.get("行號")
        if not is_blank(quote_no) and not is_blank(line):
            key = (quote_no, line)
            if key in first_row_of_key:
                duplicate_rows.setdefault(key, [first_row_of_key[key]]).append(row)
            else:
                first_row_of_key[key] = row

    for (quote_no, line), rows in duplicate_rows.items():
        listed = "、".join(str(r) for r in rows)
        for r in rows:
            issues.append(_issue(r, "行號",
                                 f"報價單號「{quote_no}」行號「{line}」重複（第 {listed} 列）；"
                                 "唯一鍵重複時不可任選其一", value=line))
    return issues
