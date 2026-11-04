"""Field-mapping page: turn an ERP-style export into the standard sheets, explicitly."""

from __future__ import annotations

import hashlib

import pandas as pd
import streamlit as st

from core.field_mapper import (
    TARGETS,
    build_standard_workbook,
    list_sheets,
    mapping_from_json,
    mapping_to_json,
    read_source,
    standardize,
    validate_mapping,
)
from core.validation import ERROR

NONE = "（不對應）"
TARGET_HELP = {
    "BOM": "每件成品用了哪些料、各用多少、原單價（單階、已展開）。",
    "ProductCost": "每件成品的人工、製費、其他成本、售價、月產量。沒有這張就不會計算毛利率。",
    "PriceIncrease": "供應商調價：料號、單位、幣別、新單價、生效日。",
    "OpenQuotes": "仍有效的客戶報價：報價單號、行號、成品、客戶、單價、數量、有效期間、狀態。",
    "RFQ": "客戶詢價：詢價單號、行號、客戶、日期、成品、數量、單位、幣別；版本不同的詢價會分開保存。",
    "BatchCost": "批次成本：每件材料、人工、製費、委外（變動成本）與每批開機、換線治具、其他固定費；"
                 "空白代表未知，0 必須明確填寫。",
    "HistoricalQuotes": "歷史報價（每個來源檔可各自存一份對應設定）：報價單號、行號、日期、客戶、成品、數量、"
                        "計價單位、幣別、單價、稅別（未稅／含稅）。",
}


def _issues_table(issues):
    return pd.DataFrame([i.to_dict() for i in issues])


def main():
    st.set_page_config(page_title="Excel 欄位對應", page_icon="🔗", layout="wide")
    st.title("Excel 欄位對應")
    st.caption("把 ERP 匯出的 Excel，依您**逐欄指定**的對應，整理成本工具的標準格式。")
    st.info("系統不會自動猜測欄位、單位、幣別或 ERP 版本，也不會補零、填 0 或合併供應商。"
            "每個欄位都由您選擇並確認；產生的檔案會保留「來源Excel列號」以便追溯。")

    cfg_file = st.file_uploader("載入既有對應設定（.json，可略過）", type=["json"], key="mapping_config")
    loaded, cfg_id = {}, "0"
    if cfg_file is not None:
        raw = cfg_file.getvalue()
        try:
            loaded = mapping_from_json(raw)
            cfg_id = hashlib.sha256(raw).hexdigest()[:8]
            st.success(f"已載入對應設定：{', '.join(loaded)}。請逐欄確認是否仍正確。")
        except ValueError as exc:
            st.error(f"無法使用這份對應設定：{exc}")

    selections: dict[str, dict] = {}
    sources = {}
    source_bytes: list[bytes] = []
    for target, schema in TARGETS.items():
        cfg = loaded.get(target, {})
        with st.expander(f"{target}：{TARGET_HELP[target]}", expanded=bool(cfg)):
            up = st.file_uploader(f"{target} 的來源 Excel", type=["xlsx"], key=f"src_{target}")
            if up is None:
                continue
            data = up.getvalue()
            sheets, issues = list_sheets(data)
            if issues:
                st.error("；".join(i.reason for i in issues))
                continue
            default_sheet = cfg.get("source_sheet")
            index = sheets.index(default_sheet) if default_sheet in sheets else None
            if default_sheet and index is None:
                st.warning(f"設定中的工作表「{default_sheet}」不在這個檔案中，請重新選擇。")
            sheet = st.selectbox("來源工作表", sheets, index=index, key=f"sheet_{target}",
                                 placeholder="請選擇工作表")
            if sheet is None:
                continue
            src = read_source(data, sheet)
            if src.data is None:
                st.error("；".join(i.reason for i in src.issues))
                continue
            st.caption(f"來源預覽（前 5 列，共 {len(src.data)} 列；第 1 列為欄位名稱）")
            st.dataframe(src.data.head(5).rename(columns={"excel_row": "Excel列號"}), hide_index=True, width="stretch")

            options = [NONE, *src.headers]
            columns = {}
            cols = st.columns(3)
            for n, col in enumerate(schema.columns):
                wanted = cfg.get("columns", {}).get(col)
                if wanted and wanted not in src.headers:
                    st.warning(f"設定中「{col}」對應的來源欄位「{wanted}」不在此工作表。")
                default = options.index(wanted) if wanted in src.headers else 0
                label = f"{col}{'（必填）' if col in schema.required else ''}"
                with cols[n % 3]:
                    choice = st.selectbox(label, options, index=default, key=f"map_{target}_{col}_{cfg_id}")
                columns[col] = None if choice == NONE else choice
            selections[target] = {"source_sheet": sheet, "columns": columns}
            sources[target] = src
            source_bytes.append(data)

    if not selections:
        st.info("請至少上傳一個來源 Excel 並選擇工作表。")
        return

    st.session_state["mapping_json"] = mapping_to_json(selections)
    # Any change to the files or the selections invalidates an earlier result.
    digest = hashlib.sha256(st.session_state["mapping_json"].encode() + b"".join(source_bytes)).hexdigest()
    if st.session_state.get("standard_digest") != digest:
        st.session_state.pop("standard_file", None)
    st.download_button("⬇️ 下載目前的對應設定（field_mapping.json）", data=st.session_state["mapping_json"],
                       file_name="field_mapping.json", mime="application/json")

    if st.button("產生標準化 Excel", type="primary", width="stretch"):
        st.session_state.pop("standard_file", None)
        all_issues, frames = [], {}
        for target, sel in selections.items():
            issues = validate_mapping(target, sel["columns"], sources[target].headers)
            all_issues += issues
            if not any(i.severity == ERROR for i in issues):
                frames[target], warn = standardize(target, sources[target].data, sel["columns"])
                all_issues += warn
        errors = [i for i in all_issues if i.severity == ERROR]
        for issue in errors:
            st.error(f"{issue.sheet}｜{issue.column}：{issue.reason}")
        warnings = [i for i in all_issues if i.severity != ERROR]
        if warnings:
            st.warning("請確認以下提醒：")
            st.dataframe(_issues_table(warnings), hide_index=True, width="stretch")
        if not errors:
            st.session_state["standard_file"] = build_standard_workbook(frames)
            st.session_state["standard_digest"] = digest
            st.success(f"已產生標準化 Excel（工作表：{', '.join(frames)}）。"
                       "請把同一個檔案分別上傳到主頁的 ①、②、③。")

    if "standard_file" in st.session_state:
        st.download_button("⬇️ 下載標準化 Excel（standardized.xlsx）", data=st.session_state["standard_file"],
                           file_name="standardized.xlsx",
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                           type="primary", width="stretch")


main()
