"""Page: 報價工作台 — batch cost, quantity tiers, version comparison and customer draft.

Internal review report and customer draft are generated and downloaded separately.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import io
from decimal import Decimal

import openpyxl
import pandas as pd
import streamlit as st

from core.batch_cost import (
    BATCH_REQUIRED,
    FIXED_COLUMNS,
    MODE_DETAILED,
    MODE_EXISTING,
    VARIABLE_COLUMNS,
    cost_model_for,
    read_batch_costs,
)
from core.calculator import calculate_cost_impact
from core.customer_draft import build_customer_draft, build_customer_draft_workbook
from core.historical_quotes import HistoricalSource, import_historical_quotes
from core.matcher import match_prices
from core.quantity_tiers import compute_quantity_tiers
from core.quote_advisor import INTERNAL_LABEL
from core.quote_versions import compare_quote_versions
from core.reader import read_bom, read_price_increase, read_sheet
from core.workbench_report import build_workbench_report

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _hash(*parts) -> str:
    h = hashlib.sha256()
    for p in parts:
        h.update(p if isinstance(p, bytes) else repr(p).encode())
    return h.hexdigest()


def _manual_batch_workbook(values: dict) -> bytes:
    """Turn the manual form into a one-row BatchCost sheet so the same validation applies."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "BatchCost"
    ws.append(BATCH_REQUIRED + ["規格圖面版次"])
    ws.append([values.get(c) for c in BATCH_REQUIRED + ["規格圖面版次"]])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def cost_section(as_of):
    st.header("① 目前成本")
    mode = st.radio("成本模式（兩種不可混用）", [MODE_EXISTING, MODE_DETAILED], key="cost_mode", horizontal=True,
                    help="既有完整單件成本：沿用主頁的 BOM＋ProductCost 計算，不另加批次費。"
                         "明細批次成本：自行提供每件變動成本與每批固定費。")
    fingerprint = [mode]
    if mode == MODE_EXISTING:
        st.caption("既有完整單件成本可能已包含批次相關費用，所以這個模式**不另加**開機、換線等批次費。")
        c1, c2, c3 = st.columns(3)
        bom = c1.file_uploader("BOM／成本 Excel（含 ProductCost）", type=["xlsx"], key="ex_bom")
        price = c2.file_uploader("供應商調價 Excel", type=["xlsx"], key="ex_price")
        product = c3.text_input("成品編號", key="ex_product")
        costs = None
        if bom and price:
            b, p = read_bom(bom.getvalue()), read_price_increase(price.getvalue())
            if b.data is None or p.data is None:
                st.error("BOM 或供應商調價檔無法讀取：" + "；".join(i.reason for i in b.issues + p.issues))
            else:
                pc = read_sheet(bom.getvalue(), "ProductCost", ["成品編號"]).data
                costs = calculate_cost_impact(match_prices(b.data, p.data, as_of), pc)
            fingerprint += [bom.getvalue(), price.getvalue()]
        fingerprint.append(product)
        return cost_model_for(product.strip(), MODE_EXISTING, as_of, costs=costs), fingerprint

    source = st.radio("批次成本來源", ["上傳 BatchCost Excel", "手動輸入"], key="detail_source", horizontal=True)
    if source == "手動輸入":
        st.caption("空白代表**未知**，系統會阻擋；確實為 0 的項目請明確輸入 0。單位：TWD、每件（pcs）。")
        c = st.columns(3)
        values = {"成品編號": c[0].text_input("成品編號", key="m_product"),
                  "規格圖面版次": c[1].text_input("規格圖面版次（選填）", key="m_version"),
                  "成本基準日": c[2].date_input("成本基準日", value=as_of, key="m_base_date"),
                  "幣別": "TWD", "單位": "pcs"}
        c = st.columns(4)
        for n, col in enumerate(VARIABLE_COLUMNS):
            values[col] = c[n].text_input(f"{col}（每件）", key=f"m_{col}")
        c = st.columns(3)
        for n, col in enumerate(FIXED_COLUMNS):
            values[col] = c[n].text_input(f"{col}（每批）", key=f"m_{col}")
        values["成本來源"] = st.text_input("成本來源（例如：標準成本表、估價單）", key="m_source")
        values["成本完整性狀態"] = "已確認" if st.checkbox("以上成本已由成本負責人確認", key="m_confirmed") else "未確認"
        values = {k: (v.strip() or None) if isinstance(v, str) else v for k, v in values.items()}
        table = read_batch_costs(_manual_batch_workbook(values))
        product, version = values["成品編號"] or "", values["規格圖面版次"]
        fingerprint.append(sorted((k, str(v)) for k, v in values.items()))
    else:
        up = st.file_uploader("BatchCost Excel（標準欄位；不同欄位名稱請先用「Excel 欄位對應」頁轉換）", type=["xlsx"],
                              key="batch_file")
        if up is None:
            st.info("請上傳 BatchCost Excel，或改用手動輸入。範例：samples/batch_cost/batch_cost_sample.xlsx")
            return None, fingerprint
        table = read_batch_costs(up.getvalue())
        products = sorted({p for p, _ in table.records} | {p for p, _ in table.blocked})
        c = st.columns(2)
        product = c[0].selectbox("成品編號", products, key="b_product") if products else ""
        version = c[1].text_input("規格圖面版次（需與資料相同）", key="b_version") or None
        fingerprint += [up.getvalue(), product, version]
    if table.issues:
        with st.expander(f"批次成本資料檢查（{len(table.issues)} 筆）", expanded=True):
            st.dataframe(pd.DataFrame([i.to_dict() for i in table.issues]), hide_index=True, width="stretch")
    return cost_model_for(product, MODE_DETAILED, as_of, batch=table, version=version), fingerprint


def history_section():
    st.header("③ 歷史報價（選填：歷史差額與版本比較）")
    up = st.file_uploader("標準化歷史報價 Excel（在「歷史報價與建議報價」頁下載）", type=["xlsx"], key="hist_std")
    if up is None:
        return None, b""
    imp = import_historical_quotes([HistoricalSource(up.name, up.getvalue(), "HistoricalQuotes")])
    if imp.records.empty:
        st.error("沒有可用的歷史報價：" + "；".join(i.reason for i in imp.issues[:3]))
        return None, up.getvalue()
    st.caption(f"已匯入 {len(imp.records)} 筆歷史報價。")
    return imp.records, up.getvalue()


def main():
    st.set_page_config(page_title="報價工作台", page_icon="🧮", layout="wide")
    st.title("報價工作台")
    st.warning(f"{INTERNAL_LABEL}。請分清楚：**歷史參考價格**（過去報價，不是成交價）、**目前完整成本**、"
               "**安全底價（試算）**（成本與毛利率算出的下限），以及**人工決定的正式售價**（只有人能填）。")
    as_of = st.date_input("試算日", value=dt.date(2026, 12, 1), key="as_of")
    model, cost_fp = cost_section(as_of)

    st.header("② 數量階梯")
    c = st.columns(3)
    qty_text = c[0].text_input("試算數量（以逗號分隔）", value="10, 100, 500", key="t_quantities")
    margin = c[1].number_input("目標毛利率（%）", min_value=0.0, max_value=99.9, value=20.0, step=0.5, key="t_margin")
    moq = c[2].text_input("最低訂購量 MOQ（選填）", key="t_moq")
    records, hist_bytes = history_section()

    tier_fp = _hash(as_of, cost_fp, qty_text, margin, moq, hist_bytes)
    if st.button("計算數量階梯", type="primary", disabled=model is None):
        try:
            result = compute_quantity_tiers(model, [q for q in qty_text.replace("，", ",").split(",") if q.strip()],
                                            Decimal(str(margin)) / 100, moq=moq.strip() or None,
                                            history_records=records, as_of=as_of)
            st.session_state["tiers"] = {"fp": tier_fp, "result": result}
        except ValueError as exc:
            st.error(str(exc))
            st.session_state.pop("tiers", None)
    tiers = st.session_state.get("tiers")
    if tiers and tiers["fp"] != tier_fp:
        st.session_state.pop("tiers", None)
        tiers = None
    if tiers:
        res = tiers["result"]
        st.caption(f"成本口徑：{res.model.basis or '；'.join(res.model.missing)}")
        st.dataframe(res.rows, hide_index=True, width="stretch")

    if records is not None:
        st.subheader("報價版本比較")
        quotes = sorted({q for q, n in zip(records["報價單號"], records.groupby(["報價單號", "報價行號"])["報價版本"]
                                                                   .transform("count")) if n > 1})
        if quotes:
            c = st.columns(5)
            qno = c[0].selectbox("報價單號（有多個版本）", quotes, key="v_quote")
            sel = records[records["報價單號"] == qno]
            line = c[1].selectbox("行號", sorted(set(sel["報價行號"])), key="v_line")
            versions = sorted({v or "" for v in sel[sel["報價行號"] == line]["報價版本"]})
            va = c[2].selectbox("版本 A", versions, key="v_a")
            vb = c[3].selectbox("版本 B", versions, index=min(1, len(versions) - 1), key="v_b")
            newer = c[4].radio("同一天時哪一版較新", ["不指定", "A", "B"], key="v_newer")
            reason = st.text_input("變更原因（人工輸入，選填）", key="v_reason")
            v_fp = _hash(hist_bytes, qno, line, va, vb, newer, reason)
            if st.button("比較兩個版本"):
                try:
                    st.session_state["versions"] = {"fp": v_fp, "result": compare_quote_versions(
                        records, qno, line, va, vb, newer=None if newer == "不指定" else newer, change_reason=reason)}
                except ValueError as exc:
                    st.error(str(exc))
            vres = st.session_state.get("versions")
            if vres and vres["fp"] == v_fp:
                st.info(vres["result"].message)
                st.dataframe(vres["result"].rows, hide_index=True, width="stretch")
            else:
                st.session_state.pop("versions", None)
        else:
            st.caption("目前的歷史報價中沒有多個版本的報價。")

    if tiers:
        vres = st.session_state.get("versions")
        report = build_workbench_report(tiers["result"], vres["result"] if vres else None)
        tiers["report"] = report
        st.download_button("⬇️ A. 下載內部覆核報告（含成本與底價，僅供內部）", report,
                           file_name="quote_workbench_internal.xlsx", mime=XLSX)

        st.header("④ 客戶報價草稿（只含客戶可以看到的資料）")
        st.caption("價格**不會**自動帶入，請由權責人員逐一填寫。空白的數量會讓草稿標示為「未核准草稿」。"
                   "本系統不寄送、不簽名、不核准。")
        c = st.columns(4)
        header = {"客戶代碼": c[0].text_input("客戶代碼", key="d_customer"),
                  "客戶名稱": c[1].text_input("客戶名稱（選填）", key="d_customer_name"),
                  "報價單號": c[2].text_input("報價單號", key="d_quote_no"),
                  "報價版本": c[3].text_input("報價版本", value="1", key="d_version")}
        c = st.columns(4)
        header["報價日期"] = c[0].date_input("報價日期", value=as_of, key="d_date")
        header["報價有效期限"] = c[1].date_input("報價有效期限", value=as_of + dt.timedelta(days=30), key="d_valid")
        header["交易條件"] = c[2].text_input("交易條件（選填）", key="d_terms")
        name = c[3].text_input("成品名稱（選填）", key="d_name")
        lines = []
        cols = st.columns(min(len(res.rows), 5) or 1)
        for n, q in enumerate(res.rows["數量"]):
            price = cols[n % len(cols)].text_input(f"{q} 件的報價單價（人工填寫）", key=f"d_price_{q}")
            lines.append({"成品編號": res.model.product, "成品名稱": name, "數量": q, "計價單位": "pcs",
                          "幣別": "TWD", "報價單價": price.strip() or None})
        confirmed = st.checkbox("以上價格已由權責人員確認（系統不會產生核准紀錄）", key="d_confirmed")
        d_fp = _hash(tier_fp, sorted((k, str(v)) for k, v in header.items()), name,
                     [l["報價單價"] for l in lines], confirmed)
        if st.button("產生客戶報價草稿"):
            try:
                draft = build_customer_draft(header, lines, prices_confirmed=confirmed)
                st.session_state["draft"] = {"fp": d_fp, "file": build_customer_draft_workbook(draft),
                                             "label": draft.label}
            except ValueError as exc:
                st.error(str(exc))
        d = st.session_state.get("draft")
        if d and d["fp"] == d_fp:
            st.info(f"草稿狀態：{d['label']}")
            st.download_button("⬇️ B. 下載客戶報價草稿（不含成本、底價與其他客戶資料）", d["file"],
                               file_name="customer_quote_draft.xlsx", mime=XLSX)
        else:
            st.session_state.pop("draft", None)


main()
