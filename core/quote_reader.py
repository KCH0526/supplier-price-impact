"""Read the OpenQuotes (open customer quotes) worksheet.

Reuses core.reader.read_sheet, so the same upload limits, header checks,
None-for-blank and Excel row numbers apply. All four identifier columns
(報價單號, 行號, 成品編號, 客戶代碼) are returned as text.
"""

from __future__ import annotations

from core.reader import SheetResult, Source, read_sheet
from core.validation import is_blank

QUOTE_SHEET = "OpenQuotes"
QUOTE_REQUIRED_COLUMNS = [
    "報價單號", "行號", "成品編號", "客戶代碼", "未稅報價單價",
    "報價幣別", "報價數量", "生效日", "截止日", "報價狀態",
]
QUOTE_ID_COLUMNS = ("報價單號", "行號", "成品編號", "客戶代碼")


def _as_text(value):
    """Numbers stored as numbers become text; leading zeros of numeric cells are already lost in Excel."""
    if is_blank(value) or isinstance(value, str) or isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return str(int(value)) if float(value).is_integer() else str(value)
    return str(value)


def read_open_quotes(source: Source) -> SheetResult:
    result = read_sheet(source, QUOTE_SHEET, QUOTE_REQUIRED_COLUMNS)
    if result.data is not None:
        for col in QUOTE_ID_COLUMNS:
            result.data[col] = [_as_text(v) for v in result.data[col]]
    return result
