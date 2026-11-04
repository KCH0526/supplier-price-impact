"""Historical quote import and standardisation (PR #16).

Rules: docs/HISTORICAL_QUOTE_PRODUCT_SPEC.md sections 3-4.

- Each source file has its own explicit column mapping (core.field_mapper),
  or already uses the standard column names (e.g. a previously downloaded
  standardised file).
- Nothing is guessed: no exchange rates, no tax conversion, no unit
  conversion, blanks stay blank, an unknown deal status is never "won".
- Identity key: 報價單號 + 報價行號 + 報價版本. Identical core fields =
  duplicate import (kept once); different core fields = conflict (all rows
  with that key are blocked). Different revisions are all kept.
- Everything stays in memory; only the user's download leaves it.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

import pandas as pd

from core.field_mapper import (
    TARGETS,
    TRACE_COLUMN,
    build_standard_workbook,
    read_source,
    standardize,
    validate_mapping,
)
from core.reader import read_sheet
from core.validation import ERROR, ROW_COLUMN, WARNING, Issue, is_blank, parse_date, parse_number

HIST_SHEET = "HistoricalQuotes"
HIST_REQUIRED = TARGETS[HIST_SHEET].required
HIST_OPTIONAL = TARGETS[HIST_SHEET].optional
SOURCE_COLUMNS = ["來源檔案", "來源工作表", TRACE_COLUMN]
COMPUTED_COLUMNS = ["可直接比較", "無法比較原因", "最新版本"]
RECORD_COLUMNS = [*HIST_REQUIRED, *HIST_OPTIONAL, *SOURCE_COLUMNS, *COMPUTED_COLUMNS]

ID_COLUMNS = ("報價單號", "報價行號", "報價版本", "客戶代碼", "成品編號", "規格圖面版次")
TEXT_REQUIRED = ("報價單號", "報價行號", "客戶代碼", "成品編號", "計價單位", "幣別")
CORE_COLUMNS = ("報價日期", "客戶代碼", "成品編號", "報價數量", "計價單位", "幣別", "報價單價", "稅別", "規格圖面版次")
DEAL_VALUES = {"成交", "未成交", "未知"}
COMPARABLE_CURRENCY = "TWD"

# Cumulative limits; single-file limits come from core.reader.
MAX_FILES = 20
MAX_TOTAL_BYTES = 100 * 1024 * 1024
MAX_TOTAL_ROWS = 100_000


@dataclass
class HistoricalSource:
    name: str
    data: bytes
    sheet: str
    columns: dict | None = None  # None: the sheet already uses the standard column names


@dataclass
class HistoricalImport:
    records: pd.DataFrame
    issues: list[Issue] = field(default_factory=list)
    summary: dict = field(default_factory=dict)


def _text(value):
    if is_blank(value):
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(int(value)) if float(value).is_integer() else str(value)
    return str(value).strip()


def _empty(issues, summary=None):
    return HistoricalImport(pd.DataFrame(columns=RECORD_COLUMNS, dtype=object), issues, summary or {})


def _relabel(issues, label):
    return [Issue(label, i.row, i.column, i.reason, i.severity, i.value) for i in issues]


def _read(src: HistoricalSource):
    """Return (rows as dicts with '_row' and '_label', issues)."""
    label = f"{src.name}｜{src.sheet}"
    if src.columns is not None:
        source = read_source(src.data, src.sheet)
        if source.data is None:
            return [], _relabel(source.issues, label)
        problems = validate_mapping(HIST_SHEET, src.columns, source.headers)
        if any(i.severity == ERROR for i in problems):
            return [], _relabel(problems, label)
        df, warns = standardize(HIST_SHEET, source.data, src.columns)
        issues = _relabel(warns, label)
        rows = df.to_dict("records")
        for r in rows:
            r["_row"] = r[TRACE_COLUMN]
            r["來源檔案"], r["來源工作表"] = src.name, src.sheet
    else:
        result = read_sheet(src.data, src.sheet, HIST_REQUIRED)
        if result.data is None:
            return [], _relabel(result.issues, label)
        issues = []
        rows = result.data.to_dict("records")
        for r in rows:
            r["_row"] = r.pop(ROW_COLUMN)
            if is_blank(r.get("來源檔案")) or is_blank(r.get(TRACE_COLUMN)):
                # A file not produced by this tool: it is itself the source.
                r["來源檔案"], r["來源工作表"], r[TRACE_COLUMN] = src.name, src.sheet, r["_row"]
    for r in rows:
        r["_label"] = label
        for col in (*HIST_REQUIRED, *HIST_OPTIONAL):
            r.setdefault(col, None)
            if isinstance(r[col], str) and not r[col].strip():
                r[col] = None
        for col in ID_COLUMNS:
            r[col] = _text(r[col])
    return rows, issues


def _validate(r) -> list[Issue]:
    label, row = r["_label"], r["_row"]
    issues = []
    for col in TEXT_REQUIRED:
        if is_blank(r[col]):
            issues.append(Issue(label, row, col, f"「{col}」不可空白", ERROR))
        else:
            r[col] = str(r[col]).strip()
    date = parse_date(r["報價日期"])
    if is_blank(r["報價日期"]):
        issues.append(Issue(label, row, "報價日期", "「報價日期」不可空白", ERROR))
    elif date is None:
        issues.append(Issue(label, row, "報價日期", "「報價日期」不是有效日期（只接受 Excel 日期或 YYYY-MM-DD）",
                            ERROR, r["報價日期"]))
    else:
        r["報價日期"] = dt.datetime(date.year, date.month, date.day)
    for col in ("報價數量", "報價單價"):
        number = parse_number(r[col])
        if is_blank(r[col]):
            issues.append(Issue(label, row, col, f"「{col}」不可空白（空白不視為 0）", ERROR))
        elif number is None or number <= 0:
            issues.append(Issue(label, row, col, f"「{col}」必須是大於 0 的有效數字", ERROR, r[col]))
        else:
            r[col] = number
    return issues


def _normalize(r) -> list[Issue]:
    label, row = r["_label"], r["_row"]
    issues = []
    tax = None if is_blank(r["稅別"]) else str(r["稅別"]).strip()
    if tax not in ("未稅", "含稅"):
        issues.append(Issue(label, row, "稅別", f"稅別「{tax or '空白'}」不明，此筆不可直接比較", WARNING, r["稅別"]))
        tax = "不明"
    r["稅別"] = tax
    deal = None if is_blank(r["成交狀態"]) else str(r["成交狀態"]).strip()
    if deal is not None and deal not in DEAL_VALUES:
        issues.append(Issue(label, row, "成交狀態", f"成交狀態「{deal}」無法辨識，視為「未知」（不視為成交）",
                            WARNING, deal))
    r["成交狀態"] = deal if deal in DEAL_VALUES else "未知"
    reasons = []
    if r["幣別"] != COMPARABLE_CURRENCY:
        reasons.append(f"幣別 {r['幣別']}，不換匯")
    if tax == "含稅":
        reasons.append("含稅價，不自動換算")
    elif tax == "不明":
        reasons.append("稅別不明")
    r["可直接比較"] = not reasons
    r["無法比較原因"] = "；".join(reasons) or None
    return issues


def _core(r):
    return tuple(r[c] for c in CORE_COLUMNS)


def _same(a, b) -> bool:
    deals_conflict = "未知" not in (a["成交狀態"], b["成交狀態"]) and a["成交狀態"] != b["成交狀態"]
    return _core(a) == _core(b) and not deals_conflict


def import_historical_quotes(sources: list[HistoricalSource]) -> HistoricalImport:
    if len(sources) > MAX_FILES:
        return _empty([Issue(None, None, None, f"一次最多匯入 {MAX_FILES} 個檔案（本次 {len(sources)} 個檔案數）", ERROR)])
    total = sum(len(s.data) for s in sources)
    if total > MAX_TOTAL_BYTES:
        return _empty([Issue(None, None, None,
                             f"檔案累計大小 {total // (1024 * 1024)} MB 超過上限 {MAX_TOTAL_BYTES // (1024 * 1024)} MB", ERROR)])

    issues: list[Issue] = []
    rows: list[dict] = []
    for src in sources:
        got, src_issues = _read(src)
        issues += src_issues
        rows += got
    if len(rows) > MAX_TOTAL_ROWS:
        return _empty(issues + [Issue(None, None, None,
                                      f"累計資料列 {len(rows):,} 列超過上限 {MAX_TOTAL_ROWS:,} 列；請分批匯入", ERROR)])

    valid = []
    for r in rows:
        problems = _validate(r)
        issues += problems
        if not any(i.severity == ERROR for i in problems):
            issues += _normalize(r)
            valid.append(r)

    groups: dict[tuple, list[dict]] = {}
    for r in valid:
        groups.setdefault((r["報價單號"], r["報價行號"], r["報價版本"] or ""), []).append(r)
    kept, skipped, blocked = [], 0, 0
    for (no, line, ver), members in groups.items():
        first = members[0]
        if all(_same(first, m) for m in members[1:]):
            kept.append(first)
            for m in members[1:]:
                skipped += 1
                issues.append(Issue(m["_label"], m["_row"], "報價單號",
                                    f"重複匯入：與 {first['來源檔案']} 第 {first[TRACE_COLUMN]} 列相同，已略過", WARNING))
        else:
            blocked += len(members)
            where = "、".join(f"{m['_label']} 第 {m['_row']} 列" for m in members)
            for m in members:
                issues.append(Issue(m["_label"], m["_row"], "報價單號",
                                    f"報價單號「{no}」行號「{line}」版本「{ver or '空白'}」資料衝突（{where}），"
                                    "無法判斷哪一筆正確，全部阻擋", ERROR))

    by_line: dict[tuple, list[dict]] = {}
    for r in kept:
        by_line.setdefault((r["報價單號"], r["報價行號"]), []).append(r)
    for (no, line), members in by_line.items():
        latest = max(m["報價日期"] for m in members)
        top = [m for m in members if m["報價日期"] == latest]
        if len(top) == 1:
            for m in members:
                m["最新版本"] = m is top[0]
        else:
            for m in members:
                m["最新版本"] = None
            issues.append(Issue(top[0]["_label"], top[0]["_row"], "報價版本",
                                f"報價單號「{no}」行號「{line}」有多個版本在同一天（{latest.date()}），無法判斷最新版本", WARNING))

    records = pd.DataFrame([{c: r.get(c) for c in RECORD_COLUMNS} for r in kept], columns=RECORD_COLUMNS, dtype=object)
    summary = {
        "檔案數": len(sources), "讀取列數": len(rows), "匯入筆數": len(records), "重複略過筆數": skipped,
        "阻擋筆數": len(rows) - len(valid) + blocked,
        "可直接比較筆數": int(sum(1 for r in kept if r["可直接比較"])),
    }
    return HistoricalImport(records, issues, summary)


def build_historical_workbook(records: pd.DataFrame) -> bytes:
    """Standardised workbook for re-import. Computed columns are recomputed on import."""
    cols = [*HIST_REQUIRED, *HIST_OPTIONAL, *SOURCE_COLUMNS]
    return build_standard_workbook({HIST_SHEET: records[cols]})
