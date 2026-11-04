"""Explicit column mapping from an ERP-style Excel export to the standard format.

The user picks, for every standard column, which source column feeds it.
Nothing is guessed: no unit or currency conversion, no zero-padding of IDs,
no filling of blanks, no merging of suppliers, no ERP-version detection.
Values are copied verbatim; only numeric identifiers are turned into text
(with a warning, because Excel may already have dropped leading zeros).

A mapping is saved as a small JSON document so it can be reused next time.
"""

from __future__ import annotations

import datetime as dt
import io
import json
from dataclasses import dataclass, field

import openpyxl
import pandas as pd

from core.quote_reader import QUOTE_REQUIRED_COLUMNS
from core.reader import SheetResult, Source, _check_archive, _load_bytes, read_sheet
from core.validation import (
    BOM_REQUIRED_COLUMNS,
    ERROR,
    PRICE_REQUIRED_COLUMNS,
    ROW_COLUMN,
    WARNING,
    Issue,
    is_blank,
)

CONFIG_FORMAT = "supplier-quote-margin-guard.field-mapping"
CONFIG_VERSION = 1
MAX_CONFIG_BYTES = 1_000_000
TRACE_COLUMN = "來源Excel列號"
ID_TARGET_COLUMNS = {"成品編號", "子件料號", "工廠代碼", "供應商代碼", "BOM版本", "報價單號", "行號", "客戶代碼",
                     "報價行號", "報價版本", "規格圖面版次"}
_FORMULA_START = ("=", "+", "-", "@")


@dataclass(frozen=True)
class TargetSchema:
    required: list[str]
    optional: list[str] = field(default_factory=list)

    @property
    def columns(self) -> list[str]:
        return [*self.required, *self.optional]


TARGETS: dict[str, TargetSchema] = {
    "BOM": TargetSchema(BOM_REQUIRED_COLUMNS, [
        "工廠代碼", "BOM版本", "BOM狀態", "生效起日", "生效迄日", "BOM基準產量", "成品單位",
        "子件類型", "行號", "供應商代碼", "原單價幣別", "原單價計價數量", "已展開至最底層",
    ]),
    "ProductCost": TargetSchema(["成品編號"], [
        "成品名稱", "未稅銷售單價", "銷售幣別", "單件人工成本", "單件製造費用", "單件其他成本", "預估月產量",
    ]),
    "PriceIncrease": TargetSchema(PRICE_REQUIRED_COLUMNS, [
        "供應商代碼", "供應商名稱", "工廠代碼", "報價單號", "計價數量", "價格迄日", "報價狀態",
    ]),
    "OpenQuotes": TargetSchema(QUOTE_REQUIRED_COLUMNS, ["客戶名稱"]),
    # Historical quotes (docs/HISTORICAL_QUOTE_PRODUCT_SPEC.md section 3).
    # Batch cost (docs/COMMERCIAL_QUOTING_SPEC.md section 3).
    "BatchCost": TargetSchema(
        ["成品編號", "成本基準日", "幣別", "單位", "單件材料變動成本", "單件人工變動成本", "單件製造費用",
         "單件委外加工費", "每批開機設定費", "每批換線治具費", "其他批次固定費", "成本來源", "成本完整性狀態"],
        ["規格圖面版次"],
    ),
    "HistoricalQuotes": TargetSchema(
        ["報價單號", "報價行號", "報價日期", "客戶代碼", "成品編號", "報價數量", "計價單位", "幣別", "報價單價", "稅別"],
        ["報價版本", "成品名稱", "規格圖面版次", "材質", "製程類別", "報價狀態", "成交狀態", "交期", "備註"],
    ),
}


@dataclass
class SourceSheet:
    headers: list[str]
    data: pd.DataFrame | None
    issues: list[Issue]


def _schema(target: str) -> TargetSchema:
    if target not in TARGETS:
        raise ValueError(f"未知的目標工作表：{target!r}")
    return TARGETS[target]


def _clean_columns(columns: dict) -> dict[str, str]:
    """Drop unmapped (blank) selections."""
    return {t: s for t, s in columns.items() if not is_blank(s)}


# ---------- source ----------

def list_sheets(source: Source) -> tuple[list[str], list[Issue]]:
    try:
        data = _load_bytes(source)
        _check_archive(data)
        wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True)
        names = list(wb.sheetnames)
        wb.close()
        return names, []
    except Exception as exc:  # noqa: BLE001 - any failure means "cannot use this file"
        return [], [Issue(None, None, None, f"無法讀取 Excel 檔案：{exc}", ERROR)]


def read_source(source: Source, sheet: str) -> SourceSheet:
    """Read any sheet: row 1 is the header, data from row 2, nothing is renamed."""
    result: SheetResult = read_sheet(source, sheet, [])
    if result.data is None:
        return SourceSheet([], None, result.issues)
    return SourceSheet([c for c in result.data.columns if c != ROW_COLUMN], result.data, result.issues)


# ---------- mapping ----------

def validate_mapping(target: str, columns: dict, headers: list[str]) -> list[Issue]:
    schema = _schema(target)
    sheet = f"欄位對應：{target}"
    mapped = _clean_columns(columns)
    issues: list[Issue] = []
    for t, s in mapped.items():
        if t not in schema.columns:
            issues.append(Issue(sheet, None, t, f"「{t}」不是 {target} 的標準欄位", ERROR))
        elif s not in headers:
            issues.append(Issue(sheet, None, t, f"來源欄位「{s}」不在所選工作表中", ERROR, s))
    used: dict[str, list[str]] = {}
    for t, s in mapped.items():
        used.setdefault(s, []).append(t)
    for s, targets in used.items():
        if len(targets) > 1:
            issues.append(Issue(sheet, None, s,
                                f"來源欄位「{s}」重複對應到 {'、'.join(targets)}；每個來源欄位只能對應一個標準欄位",
                                ERROR, s))
    for t in schema.required:
        if t not in mapped:
            issues.append(Issue(sheet, None, t, f"必要欄位「{t}」尚未指定來源欄位", ERROR))
    return issues


def standardize(target: str, data: pd.DataFrame, columns: dict) -> tuple[pd.DataFrame, list[Issue]]:
    """Copy mapped columns verbatim into the standard names. Raises on an invalid mapping."""
    headers = [c for c in data.columns if c != ROW_COLUMN]
    problems = [i for i in validate_mapping(target, columns, headers) if i.severity == ERROR]
    if problems:
        raise ValueError("；".join(i.reason for i in problems))
    mapped = _clean_columns(columns)
    order = [t for t in _schema(target).columns if t in mapped]
    numeric_ids: dict[str, list[int]] = {}
    rows = []
    for rec in data.to_dict("records"):
        out = {}
        for t in order:
            value = rec.get(mapped[t])
            if t in ID_TARGET_COLUMNS and isinstance(value, (int, float)) and not isinstance(value, bool):
                numeric_ids.setdefault(t, []).append(rec[ROW_COLUMN])
                value = str(int(value)) if float(value).is_integer() else str(value)
            out[t] = value
        out[TRACE_COLUMN] = rec[ROW_COLUMN]
        rows.append(out)
    issues = [
        Issue(target, rows_[0], t,
              f"來源欄位「{mapped[t]}」有 {len(rows_)} 筆是數值格式的識別碼（第一筆在第 {rows_[0]} 列），"
              "已轉為文字；Excel 數值格式可能已遺失前導零，系統不會自行補零，請人工確認",
              WARNING)
        for t, rows_ in numeric_ids.items()
    ]
    return pd.DataFrame(rows, columns=[*order, TRACE_COLUMN], dtype=object), issues


# ---------- output ----------

def build_standard_workbook(frames: dict[str, pd.DataFrame]) -> bytes:
    """One workbook with BOM / ProductCost / PriceIncrease / OpenQuotes sheets.

    The same file can be uploaded to all three slots of the main page.
    Text that starts with = + - @ is stored as text, never as a formula.
    """
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    for target in TARGETS:
        if target not in frames:
            continue
        df = frames[target]
        ws = wb.create_sheet(target)
        ws.append(list(df.columns))
        for r, rec in enumerate(df.to_dict("records"), start=2):
            for c, col in enumerate(df.columns, start=1):
                value = rec[col]
                cell = ws.cell(r, c)
                if is_blank(value):
                    continue
                cell.value = value
                if isinstance(value, str) and value.startswith(_FORMULA_START):
                    cell.data_type = "s"
                if col in ID_TARGET_COLUMNS:
                    cell.number_format = "@"
                elif isinstance(value, (dt.datetime, dt.date)):
                    cell.number_format = "yyyy-mm-dd"
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


# ---------- config ----------

def mapping_to_json(targets: dict[str, dict]) -> str:
    clean = {}
    for target, cfg in targets.items():
        _schema(target)
        clean[target] = {"source_sheet": cfg["source_sheet"], "columns": _clean_columns(cfg["columns"])}
    return json.dumps({"format": CONFIG_FORMAT, "version": CONFIG_VERSION, "targets": clean},
                      ensure_ascii=False, indent=2)


def mapping_from_json(text: str | bytes) -> dict[str, dict]:
    if isinstance(text, bytes):
        if len(text) > MAX_CONFIG_BYTES:
            raise ValueError("對應設定檔過大")
        text = text.decode("utf-8")
    if len(text.encode("utf-8")) > MAX_CONFIG_BYTES:
        raise ValueError("對應設定檔過大")
    try:
        doc = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"對應設定不是有效的 JSON：{exc}") from exc
    if not isinstance(doc, dict) or doc.get("format") != CONFIG_FORMAT:
        raise ValueError("不是本工具的欄位對應設定檔")
    if doc.get("version") != CONFIG_VERSION:
        raise ValueError(f"不支援的設定版本：{doc.get('version')!r}")
    targets = doc.get("targets")
    if not isinstance(targets, dict):
        raise ValueError("設定檔缺少 targets")
    result = {}
    for target, cfg in targets.items():
        schema = _schema(target)
        if not isinstance(cfg, dict) or not isinstance(cfg.get("source_sheet"), str) or not cfg["source_sheet"]:
            raise ValueError(f"{target} 缺少 source_sheet")
        columns = cfg.get("columns")
        if not isinstance(columns, dict):
            raise ValueError(f"{target} 缺少 columns")
        for t, s in columns.items():
            if t not in schema.columns:
                raise ValueError(f"{target} 沒有標準欄位「{t}」")
            if not isinstance(s, str):
                raise ValueError(f"{target}.{t} 的來源欄位必須是文字")
        result[target] = {"source_sheet": cfg["source_sheet"], "columns": _clean_columns(columns)}
    return result
