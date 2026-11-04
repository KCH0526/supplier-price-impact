"""Streamlit UI: 供應商漲價與客戶報價毛利風險覆核器 (Supplier Quote Margin Guard).

Runs locally or on a private network. Uploads are processed in memory only.
"""

from __future__ import annotations

import datetime as dt
import hashlib
from decimal import ROUND_HALF_UP, Decimal

import pandas as pd
import streamlit as st

from core.calculator import calculate_cost_impact
from core.matcher import match_prices
from core.quote_reader import read_open_quotes
from core.quote_risk import (
    DEFAULT_MIN_MARGIN,
    SCENARIO_NOTE,
    STATUS_EXCLUDED,
    STATUS_OK,
    STATUS_REVIEW,
    STATUS_UNRELIABLE,
    assess_quote_risk,
)
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


def _pct(value):
    if value is None:
        return ""
    return f"{(Decimal(value) * 100).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)}%"


def _num(value, places="0.01"):
    if value is None:
        return ""
    return f"{Decimal(value).quantize(Decimal(places), rounding=ROUND_HALF_UP):,}"


def risk_display(df):
    """Human-readable copy for the screen; the Excel file keeps full precision."""
    out = df[["風險排序", "覆核狀態", "問題原因", "客戶代碼", "報價單號", "行號", "成品編號",
              "未稅報價單價", "報價數量", "原毛利率", "新毛利率", "毛利率下降百分點",
              "報價情境成本增加", "維持底線所需最低單價", "來源Excel列號"]].copy()
    for col in ("原毛利率", "新毛利率"):
        out[col] = [_pct(v) for v in out[col]]
    for col in ("未稅報價單價", "毛利率下降百分點", "報價情境成本增加", "維持底線所需最低單價"):
        out[col] = [_num(v) for v in out[col]]
    out["報價數量"] = [_num(v, "1") for v in out["報價數量"]]
    return out


FILE_HELP = """
**三份 Excel 各放什麼？**（第 1 列是欄位名稱，資料從第 2 列開始；欄位順序不限）

| 檔案 | 工作表 | 必填欄位 |
|---|---|---|
| ① BOM／成本 | `BOM`（可另附 `ProductCost`） | 成品編號、成品名稱、子件料號、子件名稱、單位、用量（每 1 件成品）、原單價 |
| ② 供應商調價 | `PriceIncrease` | 子件料號、子件名稱、單位、幣別、新單價、生效日 |
| ③ 客戶未結報價 | `OpenQuotes` | 報價單號、行號、成品編號、客戶代碼、未稅報價單價、報價幣別、報價數量、生效日、截止日、報價狀態 |

- `ProductCost` 工作表提供每件成品的人工、製造費用、其他成本；**缺少時不會計算毛利率**。
- 目前只支援 TWD、每件（pcs）計價；不會自動換匯或換算單位。
- 範例檔在 GitHub 專案的 `samples/` 目錄，全部是合成資料。
"""


def main():
    st.set_page_config(page_title="供應商漲價與客戶報價毛利風險覆核器", page_icon="📊", layout="wide")
    st.title("供應商漲價與客戶報價毛利風險覆核器")
    st.caption("Supplier Quote Margin Guard｜供應商通知漲價後，找出哪些仍有效的客戶報價毛利會低於公司底線。")
    st.info("本工具只產生「需人工覆核」的報告：不修改 ERP、不調整或寄送客戶報價。"
            "上傳檔只在記憶體處理，請在本機或公司內網使用。")
    with st.expander("第一次使用？看三份 Excel 要準備什麼", expanded=False):
        st.markdown(FILE_HELP)

    c1, c2, c3 = st.columns(3)
    with c1:
        bom_file = st.file_uploader("① BOM／成本 Excel", type=["xlsx"], key="bom",
                                    help="工作表 BOM：每件成品用了哪些料、各用多少、原單價。")
    with c2:
        quote_file = st.file_uploader("② 供應商調價 Excel", type=["xlsx"], key="quote",
                                      help="工作表 PriceIncrease：哪些料號漲價、新單價、從哪天生效。")
    with c3:
        open_quote_file = st.file_uploader("③ 客戶未結報價 Excel（建議）", type=["xlsx"], key="open_quotes",
                                           help="工作表 OpenQuotes：還有效的客戶報價。不上傳時只產出成本影響。")
    d1, d2 = st.columns(2)
    with d1:
        as_of = st.date_input("試算基準日", value=dt.date(2026, 12, 1),
                              help="用這一天判斷供應商報價、BOM 與客戶報價是否有效；不會自動使用今天。")
    with d2:
        floor_pct = st.number_input("最低可接受毛利率（%）", min_value=0.0, max_value=99.9,
                                    value=float(DEFAULT_MIN_MARGIN * 100), step=0.5, format="%.1f",
                                    help="公司要求的毛利率底線。新毛利率低於此值的報價會列入「需人工覆核」。")
    min_margin = Decimal(str(floor_pct)) / 100

    if bom_file is None or quote_file is None:
        st.info("請至少上傳 ① BOM 與 ② 供應商調價；要檢查客戶報價毛利，請再上傳 ③。")
        return

    bom_bytes, quote_bytes = bom_file.getvalue(), quote_file.getvalue()
    open_bytes = open_quote_file.getvalue() if open_quote_file is not None else b""
    bom, quote = read_bom(bom_bytes), read_price_increase(quote_bytes)
    show_issues(bom.issues, "BOM 讀取")
    show_issues(quote.issues, "供應商報價讀取")
    open_quotes = read_open_quotes(open_bytes) if open_bytes else None
    if open_quotes is not None:
        show_issues(open_quotes.issues, "客戶報價讀取")
    if bom.data is None or quote.data is None or (open_quotes is not None and open_quotes.data is None):
        st.error("無法讀取必要工作表或欄位，請依上方明細修正檔案後重試。")
        return

    loaded = f"Excel 已讀取：BOM {len(bom.data)} 行；供應商報價 {len(quote.data)} 行"
    if open_quotes is not None:
        loaded += f"；客戶報價 {len(open_quotes.data)} 行"
    st.success(loaded + "。")
    show_issues(validate_bom(bom.data), "BOM 欄位檢核")
    show_issues(validate_price_increase(quote.data), "供應商報價欄位檢核")
    edited_costs = product_inputs(bom.data, bom_bytes)

    # Hide old results as soon as any input or assumption changes.
    digest = hashlib.sha256(bom_bytes + quote_bytes + open_bytes + as_of.isoformat().encode()
                            + str(min_margin).encode()
                            + edited_costs.to_json(orient="records").encode()).hexdigest()
    if st.button("產生毛利風險報告", type="primary", width="stretch"):
        try:
            matched = match_prices(bom.data, quote.data, as_of)
            calculated = calculate_cost_impact(matched, edited_costs)
            risk = assess_quote_risk(open_quotes.data, calculated, as_of, min_margin) if open_quotes else None
            content = build_report(matched, calculated, as_of, risk)
        except Exception as exc:
            st.error(f"無法產出報告：{exc}")
        else:
            st.session_state["latest_report"] = {
                "fingerprint": digest, "file": content, "summary": calculated.summary,
                "impact": calculated.cost_impact, "exceptions": matched.exceptions, "risk": risk,
            }

    report = st.session_state.get("latest_report")
    if not report or report["fingerprint"] != digest:
        return

    risk = report["risk"]
    if risk is not None:
        st.subheader("客戶報價毛利風險摘要")
        q = risk.summary
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("需人工覆核", q[STATUS_REVIEW], help="新毛利率低於設定底線的報價列數")
        m2.metric("尚符合設定底線", q[STATUS_OK])
        m3.metric("無法可靠判斷", q[STATUS_UNRELIABLE], help="報價或成本資料有問題，不顯示毛利數字")
        m4.metric("不納入試算", q[STATUS_EXCLUDED], help="已取消、尚未生效或已過期")
        st.metric("需人工覆核報價的情境成本增加", fmt_money(q["需人工覆核報價情境成本增加合計"]))
        st.caption(f"※ {SCENARIO_NOTE}。")

        st.subheader("需人工覆核清單（依風險排序）")
        review = risk.risk[risk.risk["覆核狀態"] == STATUS_REVIEW]
        if review.empty:
            st.success("沒有低於毛利率底線的報價。")
        else:
            st.dataframe(risk_display(review), hide_index=True, width="stretch")
        st.subheader("全部客戶報價")
        st.dataframe(risk_display(risk.risk), hide_index=True, width="stretch")
        if not risk.exceptions.empty:
            st.subheader("客戶報價例外")
            st.dataframe(risk.exceptions, hide_index=True, width="stretch")

    st.subheader("成本影響摘要")
    summary = report["summary"]
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("成品總數", summary["總成品數"])
    m2.metric("受影響成品", summary["受影響成品數"])
    m3.metric("成本不完整（需人工確認）", summary["未完成成品數"])
    m4.metric("預估每月總成本增加", fmt_money(summary["預估每月總成本增加"]))
    if summary["未完成成品數"]:
        st.error("部分成品有阻擋例外，不顯示其成本與毛利率；相關客戶報價標為「無法可靠判斷」。")
    st.dataframe(report["impact"], hide_index=True, width="stretch")
    st.subheader("BOM／供應商報價例外（阻擋與提醒）")
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
    navigation = st.navigation([
        st.Page(main, title="毛利風險報告", icon="📊", default=True),
        st.Page("pages/1_Excel_欄位對應.py", title="Excel 欄位對應", icon="🔗"),
    ])
    navigation.run()
