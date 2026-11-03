# 供應商漲價影響試算器 — ERP 實務相容 MVP 開發規格

版本：2026-11-03　｜　情境試算日期：2026-12-01　｜　幣別：TWD

> 本專案的 Excel 是 **合成測試資料**，以 SAP、Microsoft Dynamics 365、Oracle、Odoo 的公開資料模型及成本工作流程為概念依據；**不是**這些 ERP 的原生匯出格式，也不含任何真實客戶資料。

## 1. 產品定位與可行性

目標客戶是有 BOM 或材料成本表、能提供供應商新報價、但缺乏容易操作之跨成品價格衝擊分析的中小型製造／組裝／代工企業。第一版是本機或私有部署的離線分析工具，不會寫回 ERP，不代替 ERP 標準成本或財務總帳。

技術組合 Python 3.11 + Streamlit + pandas + openpyxl + pytest 足以處理中小型、**單階已展開** BOM、單幣別單位價格、有效日比較及 Excel 匯出。需要上線處理數萬列時，增加檔案大小、執行時間和記憶體限制，再由真實客戶檔案驗收。

## 2. 提供的五份工作簿

| 檔案 | 首要工作表 | 用途 |
|---|---|---|
| `sample_bom.xlsx` | `BOM` | 正常案例：40 筆 BOM 明細、6 種成品、27 種材料；`ProductCost` 有未稅售價、人工、製費與月產量；`欄位字典` 解說欄位。 |
| `sample_price_increase.xlsx` | `PriceIncrease` | 正常案例：11 筆有效調價、1 筆 M-999 不在 BOM 的報價；保留採購來源欄位。 |
| `expected_result_reference.xlsx` | `Summary`、`Cost Impact`、`Exceptions` | 預期的合成案例答案、逐行稽核、獨立數值基準和 20 項測試案例。 |
| `test_bom_edge_cases.xlsx` | `BOM` | 故意有未核准 BOM、每批基準產量非 1、未展開半成品等情境。 |
| `test_price_edge_cases.xlsx` | `PriceIncrease` | 故意有重複料號、錯單位、空價、零價、文字價格、USD、每百件報價、未生效報價、錯供應商等情境。 |

### 兩檔上傳的相容性

`sample_bom.xlsx` 的 `BOM` 工作表第 1 列為表頭，第 A:G 欄維持原始七個必填欄位：

`成品編號、成品名稱、子件料號、子件名稱、單位、用量、原單價`

`sample_price_increase.xlsx` 的 `PriceIncrease` 工作表第 1 列為表頭，第 A:F 欄維持原始六個必填欄位：

`子件料號、子件名稱、單位、幣別、新單價、生效日`

後面的擴充欄位保留實務來源資訊，不影響指定工作表的 `pandas.read_excel`。程式不得依表格「第幾欄」猜測意義，應依表頭名稱讀取。

## 3. 進入計算前的規則

### 必須保證的資料條件

1. **BOM 範圍**：一個工廠、選定的一個有效且已核准 BOM 版本、每次輸入已展開到底層的採購材料明細；不混用原料與未展開的半成品。
2. **成本單位**：`用量` 是「每一件成品」用量，`原單價` 是 TWD／BOM 單位／每 1 單位價格；其他基準不得直接相乘。
3. **價格條件**：選定試算日期 T，例如 2026-12-01，只接受 `生效日 <= T <= 價格迄日` 且報價狀態有效的價格。
4. **報價唯一性**：第一版每一材料在選定工廠、供應商與日期下最多有一筆可用新價格。重複衝突不得以「第一筆」或「最後一筆」默默取代。
5. **價格檢核**：新單價必須是有限正數；空白、0、負數、文字價格均拒絕。**合法降價**是 `新單價 > 0` 且低於原單價，應允許負的成本差額。
6. **一致性**：新舊單位、幣別、計價數量與已選供應商都要一致。MVP 不進行無依據的幣別換算或重量與件數換算。
7. **資料例外**：新報價的料號不在 BOM，例如 M-999，記錄為非阻擋例外；有 BOM 料件無有效新報價則沿用原價；**有報價但不合法**不可把價格當作不存在而沿用舊價。
8. **完整性**：某成品有一筆會影響成本的阻擋例外，就不顯示該成品為「完整計算完成」；不能因為跳過異常項而得到看似合理、實際少算的總成本。

### 配對主鍵：不要把料號配對理解為 ERP 原生主鍵

簡化測試集允許只按 `子件料號` 配對；正式客戶情境至少應確認：

- 工廠／組織（`plant` / `organization`）
- 物料料號（`item_code`）
- 指定供應商／採購來源（`vendor`）
- 價格有效日期和版本（`as_of_date`）
- 報價單位及每幾單位計價（`uom`, `price_per_qty`）

若企業使用一料多廠、多供應商、數量階梯價格、替代件或多階 BOM，需先選定成本來源和計算規則；此類情境在 MVP 以明確異常攔截。

## 4. 正確的成本計算定義

對成品 `p` 的每個底層 BOM 行 `i`：

```text
原材料單行成本_i = BOM 單件用量_i × 原單價_i
新材料單行成本_i = BOM 單件用量_i × (有效新報價_i，否則原單價_i)
單行成本增加_i = 新材料單行成本_i − 原材料單行成本_i

成品原材料成本_p = 所有 BOM 行原材料單行成本之和
成品新材料成本_p = 所有 BOM 行新材料單行成本之和
成品材料成本增加_p = 成品新材料成本_p − 成品原材料成本_p

如有完整單件非材料成本：
成品原完整成本_p = 原材料成本_p + 人工_p + 製造費用_p + 其他成本_p
成品新完整成本_p = 新材料成本_p + 人工_p + 製造費用_p + 其他成本_p
原毛利率_p = (未稅售價_p − 原完整成本_p) / 未稅售價_p
新毛利率_p = (未稅售價_p − 新完整成本_p) / 未稅售價_p

預估月成本增加_p = 單件成本增加_p × 預估月產量_p
全產品月預估成本增加 = 各成品預估月成本增加之和
```

重要限制：

- 原成本必須包含**所有** BOM 行，不能只加總有調價的新價匹配行。
- `原成本` 一詞可能指標準成本、移動平均成本或採購估價，須在 UI 與匯出檔揭露；此範例用「估算完整單件成本」。
- 如果沒有人工、製造費用及其他成本資料，只能呈現**材料成本與材料成本變動**。不得把 `售價－材料成本` 擅稱真正的毛利率。
- `Cost Impact` 欄中的 `%` 分母為原完整單件成本；原成本為 0 時百分比應空白或顯示不適用，不能是 `0%`。
- 金額以 TWD、未稅、每成品單件為基礎；使用 Decimal 或其他精確小數策略，**先完整加總再做報告顯示四捨五入**。
- 有效日要以**試算基準日**為準，不能用現在日期自動決定客戶想模擬的未來漲價。

## 5. 已核對過的驗收數值

試算日 2026-12-01，以下單件成本均包含模擬的人工和製造費用，成本與價差單位為 TWD。

| 成品 | 原成本 | 新成本 | 單件增加 | 月預估產量 | 月預估增加 |
|---|---:|---:|---:|---:|---:|
| P-1001 | 836.60 | 872.20 | 35.60 | 400 | 14,240.00 |
| P-1002 | 282.75 | 294.20 | 11.45 | 900 | 10,305.00 |
| P-1003 | 549.00 | 566.00 | 17.00 | 600 | 10,200.00 |
| P-1004 | 830.15 | 874.55 | 44.40 | 260 | 11,544.00 |
| P-1005 | 660.20 | 684.60 | 24.40 | 320 | 7,808.00 |
| P-1006 | 503.30 | 518.30 | 15.00 | 500 | 7,500.00 |
| **合計** | — | — | **147.85（每款各 1 件）** | — | **61,597.00（依各款預估月量）** |

例外清單的正常案例只有 `M-999` 未匹配，且不應阻擋 P-1001 至 P-1006 的計算。`expected_result_reference.xlsx` 有 `Line Audit`、`Expected Numbers` 與 `Acceptance Cases` 可逐行比對。

## 6. 開發工作建議（在原四個 PR 之上微調）

| PR | 目標 | 明確驗收與防呆 |
|---|---|---|
| PR1 | Excel 讀取與欄位驗證 | 支援上述兩個指定工作表及必要欄位；文字料號不丟前置零；日期及數值型別保留；空表／缺欄清楚報錯。 |
| PR2 | 嚴格配對與異常檢核 | 先把試算日定為可輸入欄位；日期、幣別、計價數量、供應商、重複、負價、BOM 有效性均明確處理；分阻擋／不阻擋例外。 |
| PR3 | 成本與售價試算 | 所有未調價材料保留原成本；小數用量、合法降價、完整成本與單位成本口徑驗證；商品別毛利率要有足夠成本資料才顯示。 |
| PR4 | 下載、摘要及 Docker | `Summary`、`Cost Impact`、`Exceptions`、可選的 `Line Audit`；清楚標註結果完整性及試算日期；月成本增額要有預估產量才顯示。 |

### 測試門檻

- `pytest` 全數通過；讀取 `sample_bom.xlsx` 和 `sample_price_increase.xlsx`，六款數字與第 5 節逐一相符。
- `test_bom_edge_cases.xlsx` + `test_price_edge_cases.xlsx`：`Acceptance Cases` 至少涵蓋 20 個檢查情境。**阻擋例外不能默默跳過**。
- 本機 `streamlit run app.py` 可上傳兩檔、顯示完整／未完成狀態、下載 Excel。
- `docker compose up --build` 能啟動，部署時不持久保存上傳內容或真實供應商報價。
- 不做 ERP API、資料庫、帳號系統、OCR、PDF、金流或多階 BOM 遞迴；有付費客戶後再決定下一版。

## 7. ERP 官方依據與注意事項

這些來源支持「欄位／邏輯在業界存在」，但**不代表本 Excel 等同該 ERP 的原生報表**。

1. Microsoft Dynamics 365 — BOM 有不同版本、生效區間、廠別、數量與成本 BOM 概念： https://learn.microsoft.com/en-us/dynamics365/supply-chain/production-control/bill-of-material-bom
2. Microsoft Dynamics 365 — planned cost versions 可做已購材料與製造成本的價格變動試算： https://learn.microsoft.com/en-us/dynamics365/supply-chain/cost-management/costing-versions
3. Microsoft Dynamics 365 — BOM Cost Roll-up 涉及 BOM 版本、路線、計算日、計算數量、廠別： https://learn.microsoft.com/en-us/dynamics365/supply-chain/cost-management/bom-calculations
4. SAP — BOM 子件單位和材料主檔換算、有效期間以及成本估算： https://help.sap.com/docs/SAP_S4HANA_ON-PREMISE/5e23dc8fe9be4fd496f8ab556667ea05/ae94d7531a4d414de10000000a174cb4.html
5. SAP — 採購訂單單位與訂單計價單位可能不同： https://help.sap.com/docs/SAP_S4HANA_CLOUD_PE/af9ef57f504840d2b81be8667206d485/af7eb65334e6b54ce10000000a174cb4.html
6. Oracle Fusion Cloud — 製造 Work Definition 報表含階層、生效日、組織及作業資訊： https://docs.oracle.com/en/cloud/saas/readiness/common/rrdem/create-manufacturing-work-definition-reports-with-additional-attributes-using-oracle-transactional-business-intelligence-or-otbi.html
7. Odoo — 供應商價目資料、BOM 與製造成本皆有獨立管理流程： https://www.odoo.com/documentation/18.0/applications/inventory_and_mrp/purchase/products/pricelist.html
8. 台灣鼎新 SmartERP — 產品結構可保存材料用量、成本資料，並支援單階／多階標準成本表、工程變更及價格異常： https://www.digiwin.com.tw/erp/manufacture
9. 台灣鼎新 — ERP BOM 的常見結構包括品號、版本、物料層級、用量、單位與成本： https://a1.digiwin.com/essay/essay-content.php?detail=1150
10. Odoo 19.0 官方中文說明 — 供應商價目表可由 XLSX／CSV 批次匯入，且 `partner_id`、`product_tmpl_id`、`min_qty`、`price` 是獨立欄位： https://www.odoo.com/documentation/19.0/zh_TW/applications/inventory_and_mrp/purchase/products/pricelist.html

## 8. 商業真實性與上線前必驗

公開 ERP 文件能證明**問題與處理邏輯真實存在**，不能證明企業會買你的服務。真實可收費性要透過至少 3–5 家目標企業的去識別化資料驗收，確認：

1. 企業能否在半小時內匯出 BOM、材料成本及調價通知？資料通常分散在哪些表？
2. 是否有品號／供應商／廠別／計價單位對應表？使用者能否選對成本口徑？
3. 工廠的採購或業務人員能否對結果逐行追溯、確認異常與重算報價？
4. 企業需要的是臨時免費試算、一次性欄位對映服務，還是週期性的供應商調價監控？
5. 資料是否允許上傳公共雲？若不允許，提供本機或客戶內網 Docker 部署。

建議先以**欄位對應＋單次調價試算＋可追溯 Excel 報告**作為 NT$3,000 試用／導入報價的實驗，不先承諾支持所有 ERP 原生匯出檔。
