"""Internal quote recommendation workbook (PR #19).

Every sheet starts with the internal-use label. Historical Evidence contains
other customers' prices and must never be handed to a customer. All text
goes through the existing formula-injection guard (core.report._safe_value).
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from io import BytesIO

import openpyxl
from openpyxl.styles import Alignment, Font, PatternFill

from core.historical_quotes import HistoricalImport
from core.quote_advisor import INTERNAL_LABEL, Advice
from core.quote_search import SHOWN
from core.report import _safe_value

SHEETS = ["Summary", "Quote Recommendation", "Historical Evidence", "Price Exceptions", "Data Quality"]
_HEAD = PatternFill("solid", fgColor="124559")
_WARN = PatternFill("solid", fgColor="F8D7DA")
_MONEY = {"報價單價", "新完整成本", "原完整成本", "安全底價", "歷史最低", "歷史中位數", "歷史最高", "最近一筆單價"}


def _value(v):
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, (dt.datetime, dt.date)):
        return v.isoformat()[:10]
    return _safe_value(v)


def _label(ws, extra=""):
    ws.append([f"{INTERNAL_LABEL}{extra}"])
    ws["A1"].font = Font(bold=True, color="9C0006")
    ws["A1"].fill = _WARN
    ws.append([])


def _pairs(ws, pairs):
    for key, val in pairs:
        ws.append([key, _value(val)])
        if key in _MONEY and val is not None:
            ws.cell(ws.max_row, 2).number_format = "#,##0.00"
    ws.column_dimensions["A"].width = 26
    ws.column_dimensions["B"].width = 90
    for row in ws.iter_rows(min_row=3, max_col=1):
        row[0].font = Font(bold=True)


def _table(ws, columns, records):
    ws.append(columns)
    for cell in ws[ws.max_row]:
        cell.font = Font(color="FFFFFF", bold=True)
        cell.fill = _HEAD
    for rec in records:
        ws.append([_value(rec.get(c)) for c in columns])
    ws.freeze_panes = "A4"
    for i, col in enumerate(columns, 1):
        ws.column_dimensions[openpyxl.utils.get_column_letter(i)].width = 48 if col in ("原因", "說明", "依據") else 16
        for row in ws.iter_rows(min_row=4, min_col=i, max_col=i):
            row[0].alignment = Alignment(vertical="top", wrap_text=col in ("原因", "說明"))
            if col in ("報價單號", "報價行號", "報價版本", "客戶代碼", "成品編號", "規格圖面版次"):
                row[0].number_format = "@"


def build_quote_memory_report(advice: Advice, imported: HistoricalImport) -> bytes:
    wb = openpyxl.Workbook()
    q, f, ref = advice.query, advice.floor, advice.reference or {}

    ws = wb.active
    ws.title = "Summary"
    _label(ws)
    _pairs(ws, [
        ("覆核狀態", advice.status), ("說明", advice.message),
        ("成品編號", q["成品編號"]), ("比較數量", q["比較數量"]), ("計價單位", q["計價單位"]),
        ("試算日", q["試算日"]), ("目標毛利率", f"{q['目標毛利率'] * 100:.2f}%"),
        ("安全底價", f["安全底價"]), ("歷史參考區間", f"{ref['最低']}～{ref['最高']}" if ref else "歷史資料不足，不提供"),
        ("警示數", len(advice.warnings)),
        ("使用限制", "本報告不是報價單，不會自動寄送或修改 ERP；歷史報價不是成交價，不代表市場願付價格"),
        ("資料保密", "Historical Evidence 含其他客戶的價格，屬內部資料，不可提供給客戶"),
    ])

    ws = wb.create_sheet("Quote Recommendation")
    _label(ws)
    _pairs(ws, [
        ("覆核狀態", advice.status), ("說明", advice.message),
        ("成品編號", q["成品編號"]), ("比較數量", q["比較數量"]), ("計價單位", q["計價單位"]),
        ("圖面版次", q["圖面版次"] or "未指定"), ("客戶代碼（僅用於標示同客戶）", q["客戶代碼"] or "未指定"),
        ("試算日", q["試算日"]), ("供應商調價生效日", q["供應商調價生效日"] or "未指定"),
        ("目標毛利率", f"{q['目標毛利率'] * 100:.2f}%"),
        ("A. 成本安全底線", "可用" if f["可用"] else "無法提供"),
        ("原完整成本", f["原完整成本"]), ("新完整成本", f["新完整成本"]), ("安全底價", f["安全底價"]),
        ("安全底價計算式", f["計算式"] or "；".join(advice.missing)),
        ("B. 歷史參考", "可參考" if ref else "歷史資料不足"),
        ("可比較筆數", ref.get("筆數")), ("歷史最低", ref.get("最低")), ("歷史中位數", ref.get("中位數")),
        ("歷史最高", ref.get("最高")), ("最近一筆單價", ref.get("最近一筆單價")), ("最近一筆日期", ref.get("最近一筆日期")),
        ("成交／未成交／未知", f"{ref['成交筆數']}／{ref['未成交筆數']}／{ref['成交狀態未知筆數']}" if ref else None),
        ("C. 缺少的必要資料", "；".join(advice.missing) or "無"),
        ("擬報價", q["擬報價"]),
        ("人工核准", "核准人：＿＿＿＿＿＿　日期：＿＿＿＿　（本系統不會自動決定或承諾售價）"),
    ])

    ws = wb.create_sheet("Historical Evidence")
    _label(ws, "｜內部資料：含其他客戶的價格，不可提供給客戶")
    _table(ws, SHOWN, advice.candidates.to_dict("records"))

    ws = wb.create_sheet("Price Exceptions")
    _label(ws)
    _table(ws, ["類型", "嚴重度", "說明", "依據"], advice.warnings)

    ws = wb.create_sheet("Data Quality")
    _label(ws)
    s = imported.summary
    _pairs(ws, [(k, s.get(k)) for k in ("檔案數", "讀取列數", "匯入筆數", "重複略過筆數", "阻擋筆數", "可直接比較筆數")])
    ws.append([])
    ws.append(["來源", "Excel列號", "欄位", "嚴重度", "原因"])
    for cell in ws[ws.max_row]:
        cell.font = Font(color="FFFFFF", bold=True)
        cell.fill = _HEAD
    for i in imported.issues:
        d = i.to_dict()
        ws.append([_value(d["工作表"]), d["Excel列號"], _value(d["欄位"]), d["嚴重度"], _value(d["原因"])])

    out = BytesIO()
    wb.save(out)
    return out.getvalue()
