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
import zipfile
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

# Resource limits for untrusted uploads. An .xlsx is a ZIP archive, so the
# archive is inspected before openpyxl parses anything (decompression bombs).
MAX_FILE_BYTES = 20 * 1024 * 1024          # compressed file size
MAX_UNCOMPRESSED_BYTES = 200 * 1024 * 1024  # sum of all archive members
MAX_COMPRESSION_RATIO = 200                 # per member larger than 1 MB
MAX_ARCHIVE_MEMBERS = 2000
MAX_DATA_ROWS = 50_000                      # per worksheet


class InputLimitError(ValueError):
    """The upload exceeds a safety limit; the reason is user-facing text."""


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


def _load_bytes(source: Source) -> bytes:
    if isinstance(source, (bytes, bytearray)):
        data = bytes(source)
    elif hasattr(source, "read"):
        if hasattr(source, "seek"):
            source.seek(0)
        data = source.read(MAX_FILE_BYTES + 1)
    else:
        if os.path.getsize(source) > MAX_FILE_BYTES:
            raise InputLimitError(f"檔案過大（上限 {MAX_FILE_BYTES // (1024 * 1024)} MB）")
        with open(source, "rb") as fh:
            data = fh.read()
    if len(data) > MAX_FILE_BYTES:
        raise InputLimitError(f"檔案過大（上限 {MAX_FILE_BYTES // (1024 * 1024)} MB）")
    return data


def _check_archive(data: bytes) -> None:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            members = zf.infolist()
    except zipfile.BadZipFile as exc:
        raise ValueError(f"不是有效的 .xlsx 檔案（{exc}）") from exc
    if len(members) > MAX_ARCHIVE_MEMBERS:
        raise InputLimitError(f"檔案結構異常：壓縮檔內含 {len(members)} 個項目")
    total = sum(m.file_size for m in members)
    if total > MAX_UNCOMPRESSED_BYTES:
        raise InputLimitError(
            f"檔案解壓縮後過大（{total // (1024 * 1024)} MB，上限 {MAX_UNCOMPRESSED_BYTES // (1024 * 1024)} MB）")
    for m in members:
        if m.file_size > 1024 * 1024 and m.file_size > MAX_COMPRESSION_RATIO * max(m.compress_size, 1):
            raise InputLimitError(f"檔案結構異常：{m.filename} 壓縮比過高，可能是解壓縮炸彈")


def _open_workbook(source: Source):
    data = _load_bytes(source)
    _check_archive(data)
    return openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)


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
            if col not in headers:
                issues.append(Issue(sheet_name, 1, col, f"缺少必要欄位「{col}」", ERROR))

        # Any non-blank header that appears more than once is ambiguous,
        # whether required or an extension column; never pick one silently.
        positions: dict[str, int] = {}
        reported: set[str] = set()
        for idx, name in enumerate(headers):
            if name is None:
                continue
            if name not in positions:
                positions[name] = idx
            elif name not in reported:
                reported.add(name)
                issues.append(Issue(
                    sheet_name, 1, name,
                    f"欄位「{name}」在第 1 列重複出現 {headers.count(name)} 次，無法判斷應使用哪一欄",
                    ERROR,
                ))
        if issues:
            return SheetResult(None, issues)

        records = []
        for excel_row, values in enumerate(rows, start=2):
            if all(is_blank(v) for v in values):
                continue
            if len(records) >= MAX_DATA_ROWS:
                return SheetResult(None, [Issue(
                    sheet_name, excel_row, None,
                    f"資料列過多（上限 {MAX_DATA_ROWS:,} 列）；請分批或先篩選必要資料", ERROR,
                )])
            record = {ROW_COLUMN: excel_row}
            for name, idx in positions.items():
                raw = values[idx] if idx < len(values) else None
                record[name] = _clean(raw, name)
            records.append(record)
    except Exception as exc:  # noqa: BLE001 - openpyxl parses lazily while iterating rows
        return SheetResult(None, [Issue(
            sheet_name, None, None, f"工作表「{sheet_name}」內容損毀，無法讀取：{exc}", ERROR,
        )])
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
