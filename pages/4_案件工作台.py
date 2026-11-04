"""Page: 案件工作台 — RFQ cases, status, quote versions, outcomes, variance, reports, backup/restore.

Storage is off by default and needs an explicit local path. The internal audit
report and the customer draft are separate downloads.
"""

from __future__ import annotations

import datetime as dt
import hashlib
from decimal import Decimal

import pandas as pd
import streamlit as st

from core.case_report import build_case_customer_draft, build_case_report, case_lines_overview
from core.case_store import ACTOR, CaseStore, StoreError, check_integrity
from core.quote_feedback import COST_ITEMS, STATUS_INCOMPLETE, STATUS_OK, record_outcome
from core.rfq import TERMINAL, TRANSITIONS, read_rfq, save_rfq_cases, validate_transition
from core.validation import is_blank, parse_number

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _dec(text, label, errors, required=True):
    if is_blank(text):
        if required:
            errors.append(f"「{label}」必須填寫")
        return None
    v = parse_number(text)
    if v is None:
        errors.append(f"「{label}」不是有效數字")
    return v


def _reason(key, label="原因（必填）"):
    return st.text_input(label, key=key)


def _store_section():
    st.subheader("① 本機資料保存")
    enabled = st.checkbox("啟用本機保存（預設關閉）", key="store_enabled")
    if not enabled:
        st.info("資料保存未啟用：本頁不會寫入任何檔案。啟用後才能建立案件、保存報價版本與結果。")
        return None
    path = st.text_input("資料庫檔案路徑（本機磁碟，例如 D:\\報價資料\\cases.db）", key="db_path")
    st.caption("請放在本機磁碟，不可放在網路共享磁碟。SQLite 檔案沒有加密，需要時請使用 BitLocker／FileVault 等磁碟加密。"
               "不支援多人同時寫入。")
    if is_blank(path):
        st.warning("請輸入資料庫檔案路徑；系統不會自行決定存放位置。")
        return None
    try:
        store = CaseStore(path.strip(), enabled=True)
        store.initialize()
    except StoreError as exc:
        st.error(str(exc))
        return None
    st.success(f"本機保存已啟用：{store.path}（資料結構版本 {store.schema_version()}）")
    return store


def _rfq_section(store):
    st.subheader("② 匯入客戶詢價（RFQ）")
    up = st.file_uploader("客戶詢價 Excel（工作表 RFQ，標準欄名）", type=["xlsx"], key="rfq_file")
    if up is None:
        return
    data = up.getvalue()
    digest = hashlib.sha256(data).hexdigest()
    imp = read_rfq(data, file_name=up.name)
    if imp.issues:
        st.warning("請確認以下資料問題（被阻擋的列不會保存）：")
        st.dataframe(pd.DataFrame([i.to_dict() for i in imp.issues]), hide_index=True, width="stretch")
    if not imp.cases:
        st.error("沒有可保存的案件。")
        return
    st.dataframe(pd.DataFrame([{"案件編號": c["case_id"], "客戶代碼": c["customer_code"], "詢價單號": c["rfq_no"],
                                "狀態": c["status"], "明細數": len(lines)} for c, lines in imp.cases]),
                 hide_index=True, width="stretch")
    saved = st.session_state.get("rfq_saved_digest")
    if saved == digest:
        st.success("已保存：這份詢價檔的案件已寫入資料庫。")
    elif saved is not None:
        st.warning("資料已變更：目前上傳的檔案與上次保存的不同，尚未保存。")
    else:
        st.warning("尚未保存：預覽的案件還沒有寫入資料庫。")
    reason = _reason("rfq_reason")
    if st.button("保存詢價案件", type="primary"):
        if is_blank(reason):
            st.error("請填寫原因後再保存。")
            return
        try:
            n = save_rfq_cases(store, imp, reason=reason.strip(), source=up.name)
        except StoreError as exc:
            st.error(str(exc))
            return
        st.session_state["rfq_saved_digest"] = digest
        st.success(f"已保存 {n} 個案件。")
        st.rerun()


def _status_section(store, case):
    st.markdown("**案件狀態**")
    options = sorted(TRANSITIONS.get(case["status"], set()))
    if case["status"] in TERMINAL or not options:
        st.info(f"案件已結案（{case['status']}），不可再變更狀態。")
        return
    new = st.selectbox("改為", options, index=None, key="new_status", placeholder="請選擇新狀態")
    reason = _reason("status_reason")
    source = st.text_input("來源（例如：客戶來信、會議，可留空）", key="status_source")
    if st.button("變更狀態"):
        if new is None or is_blank(reason):
            st.error("請選擇新狀態並填寫原因。")
            return
        try:
            store.update_case_status(case["case_id"], new, reason.strip(), source or None, validator=validate_transition)
        except StoreError as exc:
            st.error(str(exc))
            return
        st.rerun()


def _quote_section(store, case):
    st.markdown("**新增報價版本**（不會覆寫舊版本；成本以當時快照保存）")
    lines = [l["line_no"] for l in case["lines"]]
    cols = st.columns(4)
    line = cols[0].selectbox("明細行號", lines, index=None, key="q_line", placeholder="請選擇")
    price = cols[1].text_input("報價單價（人工填寫）", key="q_price")
    qty = cols[2].text_input("報價數量", key="q_qty")
    unit_cost = cols[3].text_input("預估單位成本（快照；可留空）", key="q_unit_cost")
    reason = _reason("q_reason")
    if st.button("新增報價版本"):
        errors = []
        p, q = _dec(price, "報價單價", errors), _dec(qty, "報價數量", errors)
        c = _dec(unit_cost, "預估單位成本", errors, required=False)
        if line is None:
            errors.append("請選擇明細行號")
        if is_blank(reason):
            errors.append("請填寫原因")
        for v, label in ((p, "報價單價"), (q, "報價數量")):
            if v is not None and v <= 0:
                errors.append(f"「{label}」必須大於 0")
        if errors:
            st.error("；".join(errors))
            return
        snapshot = {"unit_cost": c} if c is not None else {}
        try:
            v = store.add_quote_version(case["case_id"], line, p, q, snapshot, reason.strip())
        except StoreError as exc:
            st.error(str(exc))
            return
        st.session_state["last_saved"] = f"已保存：明細 {line} 報價版本 v{v}"
        st.rerun()


def _outcome_section(store, case, overview):
    st.markdown("**回填報價結果與實際成本**（每次回填新增一筆修訂）")
    quoted = [o["line"]["line_no"] for o in overview if o["latest"]]
    if not quoted:
        st.info("需人工確認：尚無報價版本，無法回填結果。")
        return
    line = st.selectbox("明細行號（以最新報價版本回填）", quoted, index=None, key="o_line", placeholder="請選擇")
    result = st.radio("結果", ["成交", "未成交"], index=None, key="o_result", horizontal=True)
    data, errors = {"result": result}, []
    if result == "未成交":
        data["lost_reason"] = st.text_input("未成交原因（可留空）", key="o_lost") or None
    elif result == "成交":
        cols = st.columns(2)
        won = cols[0].text_input("成交數量", key="o_won")
        act = cols[1].text_input("實際成本對應數量（須與報價、成交數量相同）", key="o_actual_qty")
        mode = st.radio("實際成本填寫方式（擇一）", ["尚未取得", "實際總成本", "明細成本"], key="o_cost_mode", horizontal=True)
        data["won_quantity"] = _dec(won, "成交數量", errors)
        data["actual_quantity"] = _dec(act, "實際成本對應數量", errors, required=mode != "尚未取得")
        if mode == "實際總成本":
            data["actual_total_cost"] = _dec(st.text_input("實際總成本", key="o_total"), "實際總成本", errors)
        elif mode == "明細成本":
            st.caption("空白代表未知，不是 0；有任一項空白時不計算實際毛利率。")
            cols = st.columns(len(COST_ITEMS))
            data["actual_cost_detail"] = {k: _dec(cols[i].text_input(k, key=f"o_{k}"), k, errors, required=False)
                                          for i, k in enumerate(COST_ITEMS)}
    reason = _reason("o_reason")
    if st.button("回填結果"):
        if line is None or result is None:
            errors.append("請選擇明細行號與結果")
        if is_blank(reason):
            errors.append("請填寫原因")
        if errors:
            st.error("；".join(errors))
            return
        version = next(o["latest"]["version"] for o in overview if o["line"]["line_no"] == line)
        try:
            r = record_outcome(store, case["case_id"], line, version, data, reason.strip())
        except StoreError as exc:
            st.error(str(exc))
            return
        st.session_state["last_saved"] = f"已保存：明細 {line} v{version} 結果修訂 r{r}"
        st.rerun()


def _variance(overview):
    rows = []
    for o in overview:
        a = o["analysis"]
        if a is None:
            rows.append({"行號": o["line"]["line_no"], "狀態": "需人工確認", "說明": "尚無報價版本"})
            continue
        rows.append({"行號": o["line"]["line_no"], "報價版本": o["latest"]["version"], "狀態": a["status"],
                     "預估毛利率%": a["estimated_margin_pct"], "實際毛利率%": a["actual_margin_pct"],
                     "成本差異": a["cost_variance"], "毛利率下降（百分點）": a["margin_drop_points"], "說明": a["message"]})
    st.dataframe(pd.DataFrame(rows).astype(str).replace({"None": "", "nan": ""}), hide_index=True, width="stretch")
    statuses = {r["狀態"] for r in rows}
    if "需人工確認" in statuses:
        st.warning("需人工確認：部分明細尚無報價版本。")
    if STATUS_INCOMPLETE in statuses:
        st.warning("成本不完整：部分明細的實際成本未填完整，不計算實際毛利率。")
    if statuses - {STATUS_OK, "需人工確認", STATUS_INCOMPLETE}:
        st.warning("需人工確認：部分明細無法分析（例如數量口徑不一致或尚無結果），請看「說明」。")


def _case_section(store):
    st.subheader("③ 案件")
    cases = store.list_cases()
    if not cases:
        st.info("資料庫中尚無案件。")
        return
    ids = [c["case_id"] for c in cases]
    case_id = st.selectbox("選擇案件", ids, index=None, key="case_id", placeholder="請選擇案件")
    if case_id is None:
        return
    case = store.get_case(case_id)
    st.write(f"客戶：{case['customer_code']}　詢價單號：{case['rfq_no']}　狀態：**{case['status']}**　"
             f"來源：{case['source_file']}")
    if msg := st.session_state.pop("last_saved", None):
        st.success(msg)
    overview = case_lines_overview(store, case_id)
    if any(o["latest"] for o in overview) and case["status"] not in ("已報價", "成交", "未成交"):
        st.warning("報價未核准：報價版本只是草稿，本系統不提供核准或簽名，正式報價須由人決定。")
    _status_section(store, case)
    _quote_section(store, case)
    overview = case_lines_overview(store, case_id)
    _outcome_section(store, case, overview)
    st.markdown("**預估與實際差異**")
    _variance(overview)

    st.markdown("**下載**（內部報告與客戶草稿分開）")
    cols = st.columns(2)
    cols[0].download_button("⬇️ 下載內部稽核報告（含成本，僅供內部）", data=build_case_report(store, case_id),
                            file_name="case_internal_report.xlsx", mime=XLSX)
    confirmed = cols[1].checkbox("報價單價已由人工確認", key="draft_confirmed")
    try:
        draft = build_case_customer_draft(store, case_id, prices_confirmed=confirmed)
        cols[1].download_button("⬇️ 下載客戶報價草稿（不含成本）", data=draft, file_name="customer_draft.xlsx", mime=XLSX)
    except ValueError as exc:
        cols[1].error(str(exc))
    st.markdown("**稽核紀錄**")
    st.caption(f"操作人：{ACTOR}，不是電子簽核。")
    st.dataframe(pd.DataFrame(store.events(case_id)).drop(columns=["id"], errors="ignore").astype(str),
                 hide_index=True, width="stretch")


def _backup_section(store):
    st.subheader("④ 備份與還原")
    st.caption("備份使用 SQLite 線上備份，不直接複製資料庫檔案；不會覆蓋已存在的備份檔。")
    default = str(store.path.with_name(f"{store.path.stem}_backup_{dt.date.today():%Y%m%d}.db"))
    dest = st.text_input("備份檔路徑", key="backup_path", placeholder=default)
    if st.button("建立備份"):
        try:
            out = store.backup((dest or default).strip())
            st.success(f"已建立備份：{out}")
        except StoreError as exc:
            st.error(str(exc))
    src = st.text_input("要還原的備份檔路徑", key="restore_path")
    if not is_blank(src):
        info = check_integrity(src.strip())
        (st.info if info["ok"] else st.error)(f"備份檔檢查：{info['message']}（資料結構版本 {info['schema_version']}）")
    confirm = st.checkbox("我確認要用這個備份覆蓋目前的資料庫（覆蓋前會自動保留一份目前資料）", key="restore_confirm")
    if st.button("還原"):
        if is_blank(src):
            st.error("請輸入備份檔路徑。")
            return
        if not confirm:
            st.error("還原會覆蓋目前資料，請先勾選確認。")
            return
        try:
            previous = store.restore(src.strip(), confirm=True)
            st.success(f"已還原。還原前的資料已保留在：{previous}")
        except StoreError as exc:
            st.error(str(exc))


def main():
    st.set_page_config(page_title="案件工作台", page_icon="📁", layout="wide")
    st.title("案件工作台")
    st.caption("管理客戶詢價案件、報價版本、成交結果與實際成本。只在本機保存；沒有登入與權限控管。")
    store = _store_section()
    if store is None:
        return
    _rfq_section(store)
    _case_section(store)
    _backup_section(store)


main()
