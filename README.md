# Supplier Price Impact

供應商漲價影響試算器。

上傳標準化 BOM／成本匯出 Excel 與供應商報價 Excel，
計算材料成本變化對成品成本的影響，並標記需人工確認的例外。

本工具不取代 ERP；它是 ERP／Excel 旁的受控試算與審核工具。
## 驗收基準

以 2026-12-01 作為調價情境日。

系統必須能根據：
- samples/sample_bom.xlsx
- samples/sample_price_increase.xlsx

產生與以下參考結果一致的材料成本影響：

| 成品 | 原單件成本 | 新單件成本 | 增加 |
|---|---:|---:|---:|
| P-1001 | 836.60 | 872.20 | +35.60 |
| P-1002 | 282.75 | 294.20 | +11.45 |
| P-1003 | 549.00 | 566.00 | +17.00 |
| P-1004 | 830.15 | 874.55 | +44.40 |
| P-1005 | 660.20 | 684.60 | +24.40 |
| P-1006 | 503.30 | 518.30 | +15.00 |

自動化測試必須使用：
- tests/fixtures/test_bom_edge_cases.xlsx
- tests/fixtures/test_price_edge_cases.xlsx
- samples/expected_result_reference.xlsx

缺少人工、製造費用或其他完整成本資料時，系統只能輸出材料成本影響，
不得宣稱或計算完整成品毛利率。
