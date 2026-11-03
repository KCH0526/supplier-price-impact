"""Basic input validation for the BOM and PriceIncrease sheets.

Scope (this PR): required values, identifiers, numbers and dates, row by row.
Business rules such as quote selection, unit / currency / supplier matching,
BOM approval status and base quantity belong to later work and are NOT
checked here.

Every problem is an ``Issue`` carrying sheet, Excel row number, column and a
reason. ``ERROR`` issues block calculation; ``WARNING`` issues do not.
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

import pandas as pd

BOM_SHEET = "BOM"
PRICE_SHEET = "PriceIncrease"

BOM_REQUIRED_COLUMNS = ["成品編號", "成品名稱", "子件料號", "子件名稱", "單位", "用量", "原單價"]
PRICE_REQUIRED_COLUMNS = ["子件料號", "子件名稱", "單位", "幣別", "新單價", "生效日"]

# Columns that hold identifiers; kept as text so leading zeros survive.
ID_COLUMNS = {"成品編號", "子件料號", "工廠代碼", "供應商代碼", "BOM版本", "報價單號"}

ROW_COLUMN = "excel_row"

ERROR = "error"
WARNING = "warning"
_SEVERITY_LABEL = {ERROR: "阻擋", WARNING: "警告"}


@dataclass(frozen=True)
class Issue:
    sheet: str | None
    row: int | None  # Excel row number (header is row 1); None for file/sheet-level issues
    column: str | None
    reason: str
    severity: str = ERROR
    value: Any = None

    @property
    def blocking(self) -> bool:
        return self.severity == ERROR

    def to_dict(self) -> dict:
        return {
            "工作表": self.sheet,
            "Excel列號": self.row,
            "欄位": self.column,
            "嚴重度": _SEVERITY_LABEL[self.severity],
            "原因": self.reason,
            "原始值": self.value,
        }


def has_blocking(issues: list[Issue]) -> bool:
    return any(i.blocking for i in issues)


# ---------- value parsing ----------

def is_blank(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, float) and value != value:  # NaN
        return True
    return isinstance(value, str) and value.strip() == ""


def parse_number(value: Any) -> Decimal | None:
    """Return a finite Decimal, or None when the value is not a usable number."""
    if is_blank(value) or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        text = repr(value) if isinstance(value, float) else str(value)
    elif isinstance(value, (str, Decimal)):
        text = str(value).strip()
    else:
        return None
    try:
        number = Decimal(text)
    except InvalidOperation:
        return None
    return number if number.is_finite() else None


_ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}", re.ASCII)


def parse_date(value: Any) -> dt.date | None:
    """Accept real Excel dates or text that is exactly YYYY-MM-DD. Bare numbers are rejected."""
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    if isinstance(value, str):
        text = value.strip()
        if not _ISO_DATE.fullmatch(text):
            return None
        try:
            return dt.date.fromisoformat(text)
        except ValueError:
            return None
    return None


# ---------- row checks ----------

def _rows(df: pd.DataFrame):
    for record in df.to_dict("records"):
        yield record.get(ROW_COLUMN), record


def _check_required_text(issues, sheet, row, record, column, severity=ERROR):
    if is_blank(record.get(column)):
        issues.append(Issue(sheet, row, column, f"「{column}」不可空白", severity))


def _check_number(issues, sheet, row, record, column, *, allow_zero, required):
    value = record.get(column)
    if is_blank(value):
        if required:
            issues.append(Issue(sheet, row, column, f"「{column}」不可空白", ERROR, value))
        return
    number = parse_number(value)
    if number is None:
        issues.append(Issue(sheet, row, column, f"「{column}」不是有效數字", ERROR, value))
    elif number < 0 or (number == 0 and not allow_zero):
        rule = "不可為負數" if allow_zero else "必須大於 0"
        issues.append(Issue(sheet, row, column, f"「{column}」{rule}", ERROR, value))


def _check_date(issues, sheet, row, record, column, *, required):
    value = record.get(column)
    if is_blank(value):
        if required:
            issues.append(Issue(sheet, row, column, f"「{column}」不可空白", ERROR, value))
        return
    if parse_date(value) is None:
        issues.append(Issue(sheet, row, column, f"「{column}」不是有效日期", ERROR, value))


def validate_bom(df: pd.DataFrame) -> list[Issue]:
    issues: list[Issue] = []
    has_line_no = "行號" in df.columns
    seen: dict[tuple, int] = {}
    for row, rec in _rows(df):
        for col in ("成品編號", "子件料號", "單位"):
            _check_required_text(issues, BOM_SHEET, row, rec, col)
        for col in ("成品名稱", "子件名稱"):
            _check_required_text(issues, BOM_SHEET, row, rec, col, severity=WARNING)
        _check_number(issues, BOM_SHEET, row, rec, "用量", allow_zero=False, required=True)
        # 原單價 ≥ 0 per the field dictionary: zero is legal.
        _check_number(issues, BOM_SHEET, row, rec, "原單價", allow_zero=True, required=True)
        for col in ("生效起日", "生效迄日"):
            if col in rec:
                _check_date(issues, BOM_SHEET, row, rec, col, required=False)
        for col in ("BOM基準產量", "原單價計價數量"):
            if col in rec:
                _check_number(issues, BOM_SHEET, row, rec, col, allow_zero=False, required=False)

        # A component may legitimately appear in many products and on several
        # lines of one product. Only an identical (product, component, line no.)
        # is suspicious, and even then it is a warning, not a blocking error.
        product, item = rec.get("成品編號"), rec.get("子件料號")
        if is_blank(product) or is_blank(item):
            continue
        key = (product, item, rec.get("行號") if has_line_no else None)
        if key in seen:
            issues.append(Issue(
                BOM_SHEET, row, "子件料號",
                f"與第 {seen[key]} 列的成品編號、子件料號{'、行號' if has_line_no else ''}相同，請確認是否重複輸入",
                WARNING, item,
            ))
        else:
            seen[key] = row
    return issues


def validate_price_increase(df: pd.DataFrame) -> list[Issue]:
    issues: list[Issue] = []
    for row, rec in _rows(df):
        for col in ("子件料號", "單位", "幣別"):
            _check_required_text(issues, PRICE_SHEET, row, rec, col)
        _check_required_text(issues, PRICE_SHEET, row, rec, "子件名稱", severity=WARNING)
        _check_number(issues, PRICE_SHEET, row, rec, "新單價", allow_zero=False, required=True)
        _check_date(issues, PRICE_SHEET, row, rec, "生效日", required=True)
        if "價格迄日" in rec:
            _check_date(issues, PRICE_SHEET, row, rec, "價格迄日", required=False)
        if "計價數量" in rec:
            _check_number(issues, PRICE_SHEET, row, rec, "計價數量", allow_zero=False, required=False)
    return issues
