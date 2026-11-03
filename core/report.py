"""Produce an auditable, presentation-ready XLSX without persisting user data."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal, ROUND_HALF_UP
from io import BytesIO

import openpyxl
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from core.calculator import CostResult, AUDIT_COLUMNS, IMPACT_COLUMNS
from core.matcher import MatchResult, EXCEPTION_COLUMNS

MONEY = {
    "原材料成本", "新材料成本", "原成本", "新成本", "成本增加", "預估月成本增加",
    "原材料金額", "新材料金額", "單行成本差額", "原單價", "試算新單價",
}
PERCENT = {"成本增加百分比", "原毛利率", "新毛利率"}
QTY = {"用量", "預估月產量"}
DATE = {"報價生效日"}


def _safe_value(value, column=""):
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, Decimal):
        if column in MONEY:
            value = value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        return float(value)
    if isinstance(value, (dt.datetime, dt.date)):
        return value.isoformat()[:10]
    if isinstance(value, str):
        # Prevent untrusted ERP-imported names/IDs from being interpreted as
        # spreadsheet formulas by Excel and other spreadsheet applications.
        if value.lstrip().startswith(("=", "+", "-", "@")) or value.startswith(("\t", "\r", "\n")):
            return "'" + value
        return value
    return value


def _table(ws, columns, dataframe):
    ws.append(columns)
    for rec in dataframe.to_dict("records"):
        ws.append([_safe_value(rec.get(col), col) for col in columns])
    ws.freeze_panes = "A2"
    if ws.max_row > 1:
        ws.auto_filter.ref = ws.dimensions
    for cell in ws[1]:
        cell.font = Font(name="Microsoft JhengHei", color="FFFFFF", bold=True)
        cell.fill = PatternFill("solid", fgColor="124559")
        cell.alignment = Alignment(vertical="center")
    ws.row_dimensions[1].height = 26
    for index, col in enumerate(columns, 1):
        for cells in ws.iter_cols(min_col=index, max_col=index, min_row=2):
            for cell in cells:
                if col in MONEY:
                    cell.number_format = '#,##0.00;[Red](#,##0.00)'
                elif col in PERCENT:
                    cell.number_format = "0.00%"
                elif col in QTY:
                    cell.number_format = '#,##0.####'
                elif col in ("成品編號", "子件料號", "供應商代碼", "報價單號"):
                    cell.number_format = "@"
                cell.alignment = Alignment(vertical="top")
        # Shorter for numeric columns; leave space for Chinese descriptions.
        width = min(48, max(14, len(col) * 2 + 3))
        if col in ("原因", "成本資料備註"):
            width = 48
        ws.column_dimensions[get_column_letter(index)].width = width


def build_report(matched: MatchResult, costs: CostResult, as_of: dt.date) -> bytes:
    """Return the result.xlsx bytes. Never writes the original uploads to disk."""
    wb = openpyxl.Workbook()
    overview = wb.active
    overview.title = "Summary"
    impact = wb.create_sheet("Cost Impact")
    exceptions = wb.create_sheet("Exceptions")
    audit = wb.create_sheet("Line Audit")

    s = costs.summary
    records = [
        ("試算基準日", as_of.isoformat()),
        ("總成品數", s["總成品數"]),
        ("可完整試算成品數", s["可完整試算成品數"]),
        ("未完成成品數", s["未完成成品數"]),
        ("受影響成品數", s["受影響成品數"]),
        ("預估每月總成本增加（TWD）", _safe_value(s["預估每月總成本增加"], "成本增加")),
        ("最高單件成本增加成品", s["最高單件成本增加成品"]),
        ("最高單件成本增加金額（TWD）", _safe_value(s["最高單件成本增加金額"], "成本增加")),
        ("資料性質", "ERP 實務相容的試算報告；不等同 ERP 正式標準成本或會計憑證"),
        ("重要提醒", "阻擋例外成品不顯示成本總額；月總額如缺產量或成品不完整則留白"),
        ("毛利率條件", "僅完整人工、製費、其他成本與有效 TWD 未稅售價皆具備時顯示"),
        ("幣別與單位", "TWD、每一件成品；不做自動幣別或單位換算"),
    ]
    for key, val in records:
        overview.append([key, val])
    overview.column_dimensions["A"].width = 34
    overview.column_dimensions["B"].width = 88
    overview.freeze_panes = "B2"
    for cell in overview["A"]:
        cell.fill = PatternFill("solid", fgColor="124559")
        cell.font = Font(name="Microsoft JhengHei", color="FFFFFF", bold=True)
    for cell in overview["B"]:
        cell.font = Font(name="Microsoft JhengHei")

    _table(impact, IMPACT_COLUMNS, costs.cost_impact)
    _table(exceptions, EXCEPTION_COLUMNS, matched.exceptions)
    _table(audit, AUDIT_COLUMNS, costs.line_audit)

    output = BytesIO()
    wb.save(output)
    wb.close()
    return output.getvalue()
