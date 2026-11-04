"""Page: 歷史報價與建議報價 (Quote Memory & Pricing Advisor). Internal use, human approval required."""

from __future__ import annotations

import datetime as dt
import hashlib
from decimal import Decimal

import pandas as pd
import streamlit as st

from core.calculator import calculate_cost_impact
from core.field_mapper import list_sheets, mapping_from_json
from core.historical_quotes import HistoricalSource, build_historical_workbook, import_historical_quotes
from core.matcher import match_prices
from core.quote_advisor import INTERNAL_LABEL, advise_quote
from core.quote_memory_report import build_quote_memory_report
from core.quote_search import search_similar_quotes
from core.reader import read_bom, read_price_increase, read_sheet

STANDARD = "（標準欄位，不需對應）"


def _hash(*parts) -> str:
    h = hashlib.sha256()
    for p in parts:
        h.update(p if isinstance(p, bytes) else str(p).encode())
    return h.hexdigest()


def _import_section():
    st.header("① 匯入歷史報價")
    st.caption("可一次選多個 .xlsx。每個檔案各自選擇欄位對應設定（在「Excel 欄位對應」頁的 HistoricalQuotes 建立並下載 .json），"
               "或選「標準欄位」直接匯入之前下載的標準化檔。")
    files = st.file_uploader("歷史報價 Excel（可多選）", type=["xlsx"], accept_multiple_files=True, key="hist_files")
    map_files = st.file_uploader("欄位對應設定 .json（可多選，可略過）", type=["json"], accept_multiple_files=True,
                                 key="hist_mappings")
    mappings = {}
    for f in map_files or []:
        try:
            cfg = mapping_from_json(f.getvalue())
            if "HistoricalQuotes" in cfg:
                mappings[f.name] = cfg["HistoricalQuotes"]
            else:
                st.warning(f"{f.name} 沒有 HistoricalQuotes 的對應設定")
        except ValueError as exc:
            st.error(f"{f.name}：無法使用這份對應設定：{exc}")
    if not files:
        st.info("請先上傳歷史報價 Excel。")
        return None

    sources, keys = [], []
    for i, f in enumerate(files):
        data = f.getvalue()
        sheets, issues = list_sheets(data)
        c1, c2 = st.columns(2)
        with c1:
            choice = st.selectbox(f"{f.name} 的欄位對應", [STANDARD, *mappings], key=f"hist_map_{i}")
        cfg = mappings.get(choice)
        if issues:
            st.error(f"{f.name}：" + "；".join(i.reason for i in issues))
            continue
        default = sheets.index(cfg["source_sheet"]) if cfg and cfg["source_sheet"] in sheets else 0
        with c2:
            sheet = st.selectbox(f"{f.name} 的工作表", sheets, index=default, key=f"hist_sheet_{i}_{choice}")
        sources.append(HistoricalSource(f.name, data, sheet, cfg["columns"] if cfg else None))
        keys.append((f.name, _hash(data), sheet, choice))

    fingerprint = _hash(*keys)
    if st.button("匯入歷史報價", type="primary"):
        st.session_state["hist_import"] = import_historical_quotes(sources)
        st.session_state["hist_fp"] = fingerprint
    if st.session_state.get("hist_fp") != fingerprint:
        st.session_state.pop("hist_import", None)
        return None
    imp = st.session_state["hist_import"]
    s = imp.summary
    m = st.columns(5)
    for col, key in zip(m, ("檔案數", "讀取列數", "匯入筆數", "重複略過筆數", "阻擋筆數")):
        col.metric(key, s.get(key, 0))
    if imp.issues:
        with st.expander(f"資料品質與匯入例外（{len(imp.issues)} 筆）", expanded=any(i.blocking for i in imp.issues)):
            st.dataframe(pd.DataFrame([i.to_dict() for i in imp.issues]), hide_index=True, width="stretch")
    if not imp.records.empty:
        st.download_button("⬇️ 下載標準化歷史報價（下次可直接匯入）", build_historical_workbook(imp.records),
                           file_name="historical_quotes_standardized.xlsx",
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    return imp


def _costs():
    st.header("② 目前成本（用來計算安全底價）")
    st.caption("上傳 BOM（含 ProductCost 工作表）與供應商調價 Excel，格式與主頁相同。不上傳就不會有安全底價。")
    c1, c2 = st.columns(2)
    with c1:
        bom_file = st.file_uploader("BOM／成本 Excel", type=["xlsx"], key="cost_bom")
    with c2:
        price_file = st.file_uploader("供應商調價 Excel", type=["xlsx"], key="cost_price")
    return bom_file, price_file


def main():
    st.set_page_config(page_title="歷史報價與建議報價", page_icon="🗂️", layout="wide")
    st.title("歷史報價與建議報價")
    st.warning(f"{INTERNAL_LABEL}。系統不會自動決定或寄送售價；歷史報價不是成交價，不代表市場願付價格。"
               "下方的歷史證據含其他客戶的價格，不可提供給客戶。")
    imp = _import_section()
    if imp is None or imp.records.empty:
        return
    bom_file, price_file = _costs()

    st.header("③ 查詢與建議")
    products = sorted(set(imp.records["成品編號"]))
    c = st.columns(4)
    product = c[0].selectbox("成品編號", products, key="q_product")
    qty = c[1].number_input("比較數量", min_value=1, value=1, step=1, key="q_qty")
    units = sorted(set(imp.records.loc[imp.records["成品編號"] == product, "計價單位"]))
    unit = c[2].selectbox("計價單位", units, key=f"q_unit_{product}")
    version = c[3].text_input("圖面版次（選填）", key="q_version")
    c = st.columns(4)
    as_of = c[0].date_input("試算日", value=dt.date(2026, 12, 1), key="q_as_of")
    margin_pct = c[1].number_input("目標毛利率（%）", min_value=0.0, max_value=99.9, value=15.0, step=0.5, key="q_margin")
    customer = c[2].text_input("客戶代碼（選填，只用來標示同客戶）", key="q_customer")
    proposed = c[3].text_input("擬報價（選填）", key="q_proposed")
    use_increase = st.checkbox("指定供應商調價生效日（檢查漲價後是否仍沿用舊價）", key="q_use_increase")
    increase = st.date_input("供應商調價生效日", value=dt.date(2026, 12, 1), key="q_increase") if use_increase else None

    bom_bytes = bom_file.getvalue() if bom_file else b""
    price_bytes = price_file.getvalue() if price_file else b""
    fingerprint = _hash(st.session_state["hist_fp"], bom_bytes, price_bytes, product, qty, unit, version, as_of,
                        margin_pct, customer, proposed, increase)
    if st.button("產生建議報價", type="primary", width="stretch"):
        with st.spinner("計算中…"):
            costs = None
            if bom_file and price_file:
                bom, price = read_bom(bom_bytes), read_price_increase(price_bytes)
                if bom.data is None or price.data is None:
                    st.error("BOM 或供應商調價檔無法讀取：" + "；".join(i.reason for i in bom.issues + price.issues))
                else:
                    pc = read_sheet(bom_bytes, "ProductCost", ["成品編號"]).data
                    costs = calculate_cost_impact(match_prices(bom.data, price.data, as_of), pc)
            search = search_similar_quotes(imp.records, product, qty, as_of, unit, drawing_version=version or None,
                                           customer=customer or None)
            advice = advise_quote(search, imp.records, costs, Decimal(str(margin_pct)) / 100,
                                  price_increase_date=increase, proposed_price=proposed or None)
            st.session_state["advice_result"] = {"fp": fingerprint, "advice": advice,
                                                 "report": build_quote_memory_report(advice, imp)}
    result = st.session_state.get("advice_result")
    if not result or result["fp"] != fingerprint:
        return
    advice = result["advice"]
    st.subheader(f"覆核狀態：{advice.status}")
    st.caption(f"※ {INTERNAL_LABEL}")
    st.markdown(f"**說明：** {advice.message}")
    f, ref = advice.floor, advice.reference
    m = st.columns(4)
    m[0].metric("新完整成本", f"{f['新完整成本']:,.2f}" if f["可用"] else "不可用")
    m[1].metric("安全底價", f"{f['安全底價']:,.2f}" if f["可用"] else "無法提供")
    m[2].metric("歷史參考區間", f"{ref['最低']:,.0f}～{ref['最高']:,.0f}" if ref else "歷史資料不足")
    m[3].metric("歷史中位數", f"{ref['中位數']:,.2f}" if ref else "—")
    if f["可用"]:
        st.caption(f"安全底價計算：{f['計算式']}")
    for item in advice.missing:
        st.error(f"缺少必要資料：{item}")
    if advice.warnings:
        st.subheader("報價異常與人工檢查原因")
        st.dataframe(pd.DataFrame(advice.warnings), hide_index=True, width="stretch")
    st.subheader("相似歷史報價（內部資料，含其他客戶價格）")
    st.dataframe(advice.candidates, hide_index=True, width="stretch")
    st.download_button("⬇️ 下載建議報價覆核報告（內部）", result["report"], file_name="quote_recommendation_internal.xlsx",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", type="primary",
                       width="stretch")


main()
