"""Read the BOM and PriceIncrease sheets from an Excel workbook.

Accepts a file path, raw bytes, or a binary file object (e.g. an upload).
Columns are matched by header name (row 1), never by position. Values are
kept as Python objects: empty cells become ``None`` (never NaN or "nan"),
identifier columns become text so leading zeros are preserved, and each
row carries its Excel row number in ``excel_row``.
"""

from __future__ import annotations

import io
import os
from dataclasses import dataclass, field
from typing import Any, BinaryIO, Union

import openpyxl
import pandas as pd

from core.validation import (
    BOM_REQUIRED_COLUMNS,
    BOM_SHEET,
    ERROR,
    ID_COLUMNS,
    PRICE_REQUIRED_COLUMNS,
    PRICE_SHEET,
    ROW_COLUMN,
    Issue,
    is_blank,
)

Source = Union[str, os.PathLike, bytes, BinaryIO]


@dataclass
class SheetResult:
    data: pd.DataFrame | None
    issues: list[Issue] = field(default_factory=list)


def _clean(value: Any, column: str) -> Any:
    if is_blank(value):
        return None
    if isinstance(value, str):
        return value.strip()
    if column in ID_COLUMNS and isinstance(value, (int, float)) and not isinstance(value, bool):
        # Excel stored the ID as a number; leading zeros (if any) are already lost.
        return str(int(value)) if float(value).is_integer() else str(value)
    return value


def _open_workbook(source: Source):
    if isinstance(source, (bytes, bytearray)):
        source = io.BytesIO(source)
    elif hasattr(source, "seek"):
        source.seek(0)
    return openpyxl.load_workbook(source, read_only=True, data_only=True)


def read_sheet(source: Source, sheet_name: str, required_columns: list[str]) -> SheetResult:
    try:
        wb = _open_workbook(source)
    except Exception as exc:  # noqa: BLE001 - any failure here means "not a readable xlsx"
        return SheetResult(None, [Issue(None, None, None, f"無法讀取 Excel 檔案：{exc}", ERROR)])

    try:
        if sheet_name not in wb.sheetnames:
            return SheetResult(None, [Issue(
                sheet_name, None, None,
                f"缺少工作表「{sheet_name}」（檔案內工作表：{'、'.join(wb.sheetnames)}）", ERROR,
            )])
        rows = wb[sheet_name].iter_rows(values_only=True)
        header_row = next(rows, None)
        if header_row is None or all(is_blank(v) for v in header_row):
            return SheetResult(None, [Issue(sheet_name, 1, None, "第 1 列沒有欄位名稱", ERROR)])

        headers = [None if is_blank(h) else str(h).strip() for h in header_row]
        issues: list[Issue] = []
        for col in required_columns:
            count = headers.count(col)
            if count == 0:
                issues.append(Issue(sheet_name, 1, col, f"缺少必要欄位「{col}」", ERROR))
            elif count > 1:
                issues.append(Issue(sheet_name, 1, col, f"必要欄位「{col}」重複出現 {count} 次", ERROR))
        if issues:
            return SheetResult(None, issues)

        # Keep the first occurrence of each named column (extension columns included).
        positions: dict[str, int] = {}
        for idx, name in enumerate(headers):
            if name is not None and name not in positions:
                positions[name] = idx

        records = []
        for excel_row, values in enumerate(rows, start=2):
            if all(is_blank(v) for v in values):
                continue
            record = {ROW_COLUMN: excel_row}
            for name, idx in positions.items():
                raw = values[idx] if idx < len(values) else None
                record[name] = _clean(raw, name)
            records.append(record)
    finally:
        wb.close()

    if not records:
        return SheetResult(None, [Issue(sheet_name, None, None, "工作表沒有資料列", ERROR)])

    # dtype=object keeps None as None (pandas would otherwise turn it into NaN).
    df = pd.DataFrame(records, columns=[ROW_COLUMN, *positions], dtype=object)
    return SheetResult(df, [])


def read_bom(source: Source) -> SheetResult:
    return read_sheet(source, BOM_SHEET, BOM_REQUIRED_COLUMNS)


def read_price_increase(source: Source) -> SheetResult:
    return read_sheet(source, PRICE_SHEET, PRICE_REQUIRED_COLUMNS)
