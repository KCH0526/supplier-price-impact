"""Streamlit UI for a local/private supplier price impact workbook."""

from __future__ import annotations

import datetime as dt
import hashlib
from decimal import Decimal

import pandas as pd
import streamlit as st

from core.calculator import calculate_cost_impact
from core.matcher import match_prices
from core.reader import read_bom, read_price_increase, read_sheet
from core.report import build_report
from core.validation import ERROR, validate_bom, validate_price_increase

INPUT_COLUMNS = [
    "成品編號", "未稅銷售單價", "單件人工成本", "單件製造費用", "單件其他成本", "預估月產量", "銷售幣別",
]
NUMERIC_COLUMNS = INPUT_COLUMNS[1:-1]


def show_issues(issues, heading):
    if not issues:
        return
    errors = sum(i.severity == ERROR for i in issues)
    if errors:
        st.warning(f"{heading}：{errors} 項阻擋問題；受影響成品將無法產出完整成本。")
    else:
        st.info(f"{heading}：{len(issues)} 項提醒。")
    with st.expander(f"查看{heading}明細", expanded=bool(errors)):
        st.dataframe(pd.DataFrame([i.to_dict() for i in issues]), hide_index=True, width="stretch")


def product_inputs(bom_data, bom_bytes):
    """ProductCost sheet is optional; empty fields remain empty, not inferred."""
    optional = read_sheet(bom_bytes, "ProductCost", ["成品編號"])
    if optional.data is None:
        if optional.issues and not any("缺少工作表" in i.reason for i in optional.issues):
            st.warning("ProductCost 工作表無法讀取；本次僅提供材料成本，不會推測人工或毛利率。")
        source = pd.DataFrame({"成品編號": bom_data["成品編號"].drop_duplicates().tolist()})
    else:
        source = optional.data.copy()
    for col in INPUT_COLUMNS:
        if col not in source:
            source[col] = None
    source = source[INPUT_COLUMNS].copy()
    for col in NUMERIC_COLUMNS:
        source[col] = pd.to_numeric(source[col], errors="coerce")
    # Never infer a missing sale currency. It must be explicitly provided
    # before the calculator is allowed to present gross margins.
    source["銷售幣別"] = source["銷售幣別"].fillna("")
    with st.expander("成本／售價／月產量（可選填；來自 BOM 檔的 ProductCost 工作表）", expanded=False):
        st.caption("可在下表直接調整數值；留空表示資料未知。只有人工、製費、其他成本與 TWD 未稅售價都有效時，才會計算完整毛利率。")
        edited = st.data_editor(
            source,
            hide_index=True,
            num_rows="fixed",
            width="stretch",
            disabled=["成品編號"],
            column_config={
                "成品編號": st.column_config.TextColumn("成品編號"),
                "未稅銷售單價": st.column_config.NumberColumn("未稅銷售單價", min_value=0.0),
                "單件人工成本": st.column_config.NumberColumn("單件人工成本", min_value=0.0),
                "單件製造費用": st.column_config.NumberColumn("單件製造費用", min_value=0.0),
                "單件其他成本": st.column_config.NumberColumn("單件其他成本", min_value=0.0),
                "預估月產量": st.column_config.NumberColumn("預估月產量", min_value=0.0),
            },
            key=f"product_cost_editor_{hashlib.sha256(bom_bytes).hexdigest()[:12]}",
        )
    return edited


def fmt_money(value):
    return "資料不足" if value is None else f"NT$ {Decimal(value):,.2f}"


def main():
    st.set_page_config(page_title="供應商漲價影響試算器", page_icon="📊", layout="wide")
    st.title("供應商漲價影響試算器")
    st.caption("適用台灣製造／組裝／代工企業的 Excel 離線試算。上傳 BOM 和供應商報價，查出受影響成品、成本、毛利與阻擋例外。")
    st.info("這是 ERP 匯出資料的試算工具，不是 ERP 正式標準成本、會計憑證或原生介接。範例檔為合成資料。")
    c1, c2 = st.columns(2)
    with c1:
        bom_file = st.file_uploader("① BOM／成本匯出 Excel（BOM 工作表）", type=["xlsx"], key="bom")
    with c2:
        quote_file = st.file_uploader("② 供應商新報價 Excel（PriceIncrease 工作表）", type=["xlsx"], key="quote")
    as_of = st.date_input("試算基準日", value=dt.date(2026, 12, 1), help="以這一天判斷報價與 BOM 的有效期間，不會自動使用今天日期。")
    st.caption("需要範例？請使用 GitHub 專案 samples/ 目錄中的兩份 .xlsx。")

    if bom_file is None or quote_file is None:
        st.info("請先選取兩個 .xlsx 檔案。")
        return

    bom_bytes, quote_bytes = bom_file.getvalue(), quote_file.getvalue()
    bom, quote = read_bom(bom_bytes), read_price_increase(quote_bytes)
    show_issues(bom.issues, "BOM 讀取")
    show_issues(quote.issues, "供應商報價讀取")
    if bom.data is None or quote.data is None:
        st.error("無法讀取必要工作表或欄位，請按上方明細修正檔案後重試。")
        return

    st.success(f"Excel 已讀取：BOM {len(bom.data)} 行；報價 {len(quote.data)} 行。")
    show_issues(validate_bom(bom.data), "BOM 欄位檢核")
    show_issues(validate_price_increase(quote.data), "報價欄位檢核")
    edited_costs = product_inputs(bom.data, bom_bytes)

    # Hide old results as soon as files, scenario date or editable assumptions change.
    digest = hashlib.sha256(bom_bytes + quote_bytes + as_of.isoformat().encode()
                            + edited_costs.to_json(orient="records").encode()).hexdigest()
    if st.button("產生報告", type="primary", width="stretch"):
        try:
            matched = match_prices(bom.data, quote.data, as_of)
            calculated = calculate_cost_impact(matched, edited_costs)
            content = build_report(matched, calculated, as_of)
        except Exception as exc:
            st.error(f"無法產出報告：{exc}")
        else:
            st.session_state["latest_report"] = {
                "fingerprint": digest, "file": content,
                "summary": calculated.summary,
                "impact": calculated.cost_impact,
                "exceptions": matched.exceptions,
            }

    report = st.session_state.get("latest_report")
    if not report or report["fingerprint"] != digest:
        return

    st.subheader("試算摘要")
    summary = report["summary"]
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("成品總數", summary["總成品數"])
    m2.metric("受影響成品", summary["受影響成品數"])
    m3.metric("需人工確認", summary["未完成成品數"])
    m4.metric("預估每月總成本增加", fmt_money(summary["預估每月總成本增加"]))
    if summary["未完成成品數"]:
        st.error("部分成品有阻擋例外；其原成本、新成本及毛利率不顯示數字。請下載 Exceptions 明細人工確認。")
    st.subheader("成品成本影響")
    st.dataframe(report["impact"], hide_index=True, width="stretch")
    st.subheader("資料例外與待確認")
    if report["exceptions"].empty:
        st.success("本次沒有資料例外。")
    else:
        st.dataframe(report["exceptions"], hide_index=True, width="stretch")
    st.download_button(
        "⬇️ 下載可稽核 Excel 報告（result.xlsx）",
        data=report["file"], file_name="result.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        type="primary", width="stretch",
    )


if __name__ == "__main__":
    main()
