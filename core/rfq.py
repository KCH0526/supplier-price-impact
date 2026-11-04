"""Customer RFQ import and case status workflow (PR #33).

- Columns: explicit mapping (core.field_mapper) or the standard names.
- Required identifiers are never guessed; invalid rows are blocked with a reason.
- A case is one customer + RFQ number + RFQ version; other versions are separate
  cases, never duplicates. Identical rows are kept once; conflicting rows with
  the same key are all blocked.
- Status changes follow TRANSITIONS; the operator is a manual note, not an
  authenticated approval.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from core.case_store import CaseStore, StoreError
from core.field_mapper import TARGETS, TRACE_COLUMN, read_source, standardize, validate_mapping
from core.reader import Source, read_sheet
from core.validation import ERROR, ROW_COLUMN, WARNING, Issue, is_blank, parse_date, parse_number

RFQ_SHEET = "RFQ"
RFQ_REQUIRED = TARGETS[RFQ_SHEET].required
STATUSES = ["待確認資料", "待估價", "待人工覆核", "已產生報價草稿", "已報價", "成交", "未成交", "作廢"]
TERMINAL = {"成交", "未成交", "作廢"}
TRANSITIONS = {
    "待確認資料": {"待估價", "作廢"},
    "待估價": {"待人工覆核", "待確認資料", "作廢"},
    "待人工覆核": {"已產生報價草稿", "待估價", "作廢"},
    "已產生報價草稿": {"已報價", "待人工覆核", "作廢"},
    "已報價": {"成交", "未成交", "待人工覆核", "作廢"},
    "成交": set(), "未成交": set(), "作廢": set(),
}


@dataclass
class RFQImport:
    cases: list = field(default_factory=list)     # [(case dict, [line dict, ...]), ...]
    issues: list[Issue] = field(default_factory=list)


def validate_transition(old: str, new: str) -> None:
    if new not in STATUSES:
        raise StoreError(f"未知的案件狀態「{new}」")
    if new not in TRANSITIONS.get(old, set()):
        allowed = "、".join(sorted(TRANSITIONS.get(old, set()))) or "無（已結案）"
        raise StoreError(f"狀態不可由「{old}」改為「{new}」；可改為：{allowed}")


def _text(v):
    if is_blank(v):
        return None
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return str(int(v)) if float(v).is_integer() else str(v)
    return str(v).strip()


def read_rfq(source: Source, sheet: str = RFQ_SHEET, columns: dict | None = None, file_name: str | None = None) -> RFQImport:
    result = RFQImport()
    name = file_name or getattr(source, "name", None) or "RFQ"
    if columns is not None:
        src = read_source(source, sheet)
        if src.data is None:
            result.issues = src.issues
            return result
        problems = [i for i in validate_mapping(RFQ_SHEET, columns, src.headers) if i.severity == ERROR]
        if problems:
            result.issues = problems
            return result
        df, result.issues = standardize(RFQ_SHEET, src.data, columns)
        rows = [dict(r, **{ROW_COLUMN: r[TRACE_COLUMN]}) for r in df.to_dict("records")]
    else:
        read = read_sheet(source, sheet, RFQ_REQUIRED)
        if read.data is None:
            result.issues = read.issues
            return result
        rows = read.data.to_dict("records")
    if hasattr(source, "name") and file_name is None:
        name = getattr(source, "name")
    name = str(name).split("/")[-1]

    groups: dict[str, dict] = {}
    seen: dict[tuple, tuple] = {}
    invalid_cases: set[str] = set()
    for r in rows:
        row = r[ROW_COLUMN]
        errors = []
        ids = {c: _text(r.get(c)) for c in ("詢價單號", "詢價行號", "客戶代碼", "成品編號", "計價單位", "幣別")}
        for col, val in ids.items():
            if val is None:
                errors.append(Issue(sheet, row, col, f"「{col}」不可空白（不會自行推測）", ERROR))
        date = parse_date(r.get("詢價日期"))
        if date is None:
            errors.append(Issue(sheet, row, "詢價日期", "「詢價日期」不是有效日期", ERROR, r.get("詢價日期")))
        qty = parse_number(r.get("詢價數量"))
        if qty is None or qty <= 0:
            errors.append(Issue(sheet, row, "詢價數量", "「詢價數量」必須是大於 0 的數字（空白不視為 0）", ERROR,
                                r.get("詢價數量")))
        due = r.get("要求交期")
        due_date = parse_date(due) if not is_blank(due) else None
        if not is_blank(due) and due_date is None:
            errors.append(Issue(sheet, row, "要求交期", "「要求交期」不是有效日期", ERROR, due))
        version = _text(r.get("詢價版本")) or "-"
        case_id = None
        if ids["客戶代碼"] and ids["詢價單號"]:
            case_id = f"{ids['客戶代碼']}|{ids['詢價單號']}|v{version}"
        result.issues += errors
        if errors:
            if case_id:
                invalid_cases.add(case_id)
            continue
        line = {"line_no": ids["詢價行號"], "product": ids["成品編號"], "drawing_version": _text(r.get("規格圖面版次")),
                "quantity": qty, "unit": ids["計價單位"], "currency": ids["幣別"],
                "required_date": due_date.isoformat() if due_date else None, "source_sheet": sheet, "source_row": row}
        key = (case_id, line["line_no"])
        content = tuple(v for k, v in line.items() if k not in ("source_row",)) + (date,)
        if key in seen:
            if seen[key][0] == content:
                result.issues.append(Issue(sheet, row, "詢價行號", f"與第 {seen[key][1]} 列完全相同，視為重複，只保留一筆", WARNING))
            else:
                result.issues.append(Issue(sheet, row, "詢價行號",
                                           f"案件 {case_id} 行號 {line['line_no']} 與第 {seen[key][1]} 列內容衝突，全部阻擋", ERROR))
                groups[case_id]["blocked"].add(line["line_no"])
            continue
        seen[key] = (content, row)
        g = groups.setdefault(case_id, {"case": {"case_id": case_id, "customer_code": ids["客戶代碼"],
                                                 "rfq_no": ids["詢價單號"], "rfq_date": date.isoformat(),
                                                 "status": "待估價", "source_file": name},
                                        "lines": [], "blocked": set()})
        g["lines"].append(line)

    for case_id, g in groups.items():
        lines = [l for l in g["lines"] if l["line_no"] not in g["blocked"]]
        if not lines:
            continue
        if g["blocked"] or case_id in invalid_cases:
            g["case"]["status"] = "待確認資料"
        result.cases.append((g["case"], lines))
    return result


def save_rfq_cases(store: CaseStore, rfq: RFQImport, reason: str, source: str = "RFQ 匯入") -> int:
    """Save every imported case; an existing case id is refused (never overwritten)."""
    existing = [c["case_id"] for c, _ in rfq.cases if store.get_case(c["case_id"]) is not None]
    if existing:
        raise StoreError(f"以下案件已存在，不會覆寫，本次未保存任何案件：{'、'.join(existing)}")
    for case, lines in rfq.cases:
        store.add_case(case, lines, reason=reason, source=source)
    return len(rfq.cases)
