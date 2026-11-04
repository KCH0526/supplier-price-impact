"""Case workbench reports (PR #35).

- build_case_report: internal 6-sheet audit workbook (costs, actuals, variance,
  exceptions, audit trail). Every sheet carries the internal-use label and all
  text goes through the formula-injection guard.
- build_case_customer_draft: the customer draft, built only through the
  allow-list in core.customer_draft (no cost, actual cost, price floor or other
  customers' data can reach it).
"""

from __future__ import annotations

from io import BytesIO

import openpyxl

from core.case_store import CaseStore
from core.customer_draft import build_customer_draft, build_customer_draft_workbook
from core.quote_feedback import COST_ITEMS, STATUS_OK, analyze
from core.quote_memory_report import _label, _pairs, _table

SHEETS = ["Case Summary", "Quotation Snapshot", "Actual Cost", "Variance Analysis", "Exceptions", "Audit Trail"]
QUOTE_COLUMNS = ["行號", "成品編號", "報價版本", "報價單價", "數量", "預估單位成本", "建立時間", "原因"]
ACTUAL_COLUMNS = ["行號", "報價版本", "修訂", "結果", "成交數量", "實際成本數量", "實際總成本", *COST_ITEMS,
                  "未成交原因", "回填時間", "原因"]
VARIANCE_COLUMNS = ["行號", "成品編號", "報價版本", "結果修訂", "狀態", "預估營收", "預估成本", "預估毛利率%",
                    "實際成本", "實際利潤", "實際毛利率%", "成本差異", "毛利率下降（百分點）", "說明"]
EXCEPTION_COLUMNS = ["行號", "類型", "說明"]
AUDIT_COLUMNS = ["時間", "對象", "動作", "舊值", "新值", "原因", "操作人", "來源"]


def case_lines_overview(store: CaseStore, case_id: str) -> list[dict]:
    """Per line: latest quote version, latest outcome revision and its analysis."""
    case = store.get_case(case_id)
    if case is None:
        raise ValueError(f"找不到案件 {case_id}")
    out = []
    for line in case["lines"]:
        versions = store.quote_versions(case_id, line["line_no"])
        latest = versions[-1] if versions else None
        outcomes = store.outcomes(case_id, line["line_no"], latest["version"]) if latest else []
        outcome = outcomes[-1] if outcomes else None
        out.append({"line": line, "versions": versions, "latest": latest, "outcomes": outcomes,
                    "outcome": outcome, "analysis": analyze(latest, outcome["data"] if outcome else None) if latest else None})
    return out


def build_case_report(store: CaseStore, case_id: str) -> bytes:
    case = store.get_case(case_id)
    if case is None:
        raise ValueError(f"找不到案件 {case_id}")
    overview = case_lines_overview(store, case_id)
    wb = openpyxl.Workbook()

    ws = wb.active
    ws.title = SHEETS[0]
    _label(ws)
    _pairs(ws, [("案件編號", case["case_id"]), ("客戶代碼", case["customer_code"]), ("詢價單號", case["rfq_no"]),
                ("詢價日期", case["rfq_date"]), ("案件狀態", case["status"]), ("來源檔案", case["source_file"]),
                ("明細數", len(case["lines"])), ("建立時間", case["created_at"]), ("最後更新", case["updated_at"]),
                ("操作人", "所有操作人欄位均為人工填寫，未經身分驗證，不是電子簽核"),
                ("資料保密", "本報告含成本、實際成本與毛利，僅供內部；給客戶的文件請使用「客戶報價草稿」")])

    ws = wb.create_sheet(SHEETS[1])
    _label(ws, "（報價當時的成本快照，不會被覆寫）")
    _table(ws, QUOTE_COLUMNS, [
        {"行號": o["line"]["line_no"], "成品編號": o["line"]["product"], "報價版本": v["version"],
         "報價單價": v["unit_price"], "數量": v["quantity"], "預估單位成本": v["cost_snapshot"].get("unit_cost"),
         "建立時間": v["created_at"], "原因": v["reason"]}
        for o in overview for v in o["versions"]])

    ws = wb.create_sheet(SHEETS[2])
    _label(ws, "（每次回填都新增修訂，舊修訂保留）")
    rows = []
    for o in overview:
        for v in o["versions"]:
            for r in store.outcomes(case_id, o["line"]["line_no"], v["version"]):
                d = r["data"]
                detail = d.get("actual_cost_detail") or {}
                rows.append({"行號": o["line"]["line_no"], "報價版本": v["version"], "修訂": r["revision"],
                             "結果": d.get("result"), "成交數量": d.get("won_quantity"),
                             "實際成本數量": d.get("actual_quantity"), "實際總成本": d.get("actual_total_cost"),
                             **{k: detail.get(k) for k in COST_ITEMS}, "未成交原因": d.get("lost_reason"),
                             "回填時間": r["recorded_at"], "原因": r["reason"]})
    _table(ws, ACTUAL_COLUMNS, rows)

    ws = wb.create_sheet(SHEETS[3])
    _label(ws, "（以最新報價版本與最新回填修訂比較）")
    variance, exceptions = [], []
    for o in overview:
        no = o["line"]["line_no"]
        if o["latest"] is None:
            exceptions.append({"行號": no, "類型": "需人工確認", "說明": "尚無報價版本"})
            continue
        a = o["analysis"]
        variance.append({"行號": no, "成品編號": o["line"]["product"], "報價版本": o["latest"]["version"],
                         "結果修訂": o["outcome"]["revision"] if o["outcome"] else None, "狀態": a["status"],
                         "預估營收": a["estimated_revenue"], "預估成本": a["estimated_cost"],
                         "預估毛利率%": a["estimated_margin_pct"], "實際成本": a["actual_cost"],
                         "實際利潤": a["actual_profit"], "實際毛利率%": a["actual_margin_pct"],
                         "成本差異": a["cost_variance"], "毛利率下降（百分點）": a["margin_drop_points"],
                         "說明": a["message"]})
        if a["estimated_margin_pct"] is None:
            exceptions.append({"行號": no, "類型": "成本不完整", "說明": "報價成本快照沒有單位成本，無法計算預估毛利"})
        if a["status"] != STATUS_OK:
            exceptions.append({"行號": no, "類型": a["status"], "說明": a["message"]})
    _table(ws, VARIANCE_COLUMNS, variance)

    ws = wb.create_sheet(SHEETS[4])
    _label(ws)
    _table(ws, EXCEPTION_COLUMNS, exceptions)

    ws = wb.create_sheet(SHEETS[5])
    _label(ws, "（操作人為人工填寫，未經身分驗證）")
    _table(ws, AUDIT_COLUMNS, [{"時間": e["at"], "對象": e["entity"], "動作": e["action"], "舊值": e["old_value"],
                                "新值": e["new_value"], "原因": e["reason"], "操作人": e["actor"], "來源": e["source"]}
                               for e in store.events(case_id)])
    out = BytesIO()
    wb.save(out)
    return out.getvalue()


def build_case_customer_draft(store: CaseStore, case_id: str, prices_confirmed: bool, header: dict | None = None) -> bytes:
    """Customer draft from the latest quote version of each line (allow-list only)."""
    case = store.get_case(case_id)
    if case is None:
        raise ValueError(f"找不到案件 {case_id}")
    lines = []
    for o in case_lines_overview(store, case_id):
        latest = o["latest"]
        lines.append({"成品編號": o["line"]["product"], "規格圖面版次": o["line"].get("drawing_version"),
                      "數量": latest["quantity"] if latest else o["line"]["quantity"], "計價單位": o["line"]["unit"],
                      "幣別": o["line"]["currency"], "報價單價": latest["unit_price"] if latest else None,
                      "交期": o["line"].get("required_date")})
    head = {"客戶代碼": case["customer_code"], "報價單號": case["rfq_no"], **(header or {})}
    return build_customer_draft_workbook(build_customer_draft(head, lines, prices_confirmed))
