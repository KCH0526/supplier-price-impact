# Supplier Price Impact

供應商漲價影響試算器。

上傳標準化 BOM／成本匯出 Excel 與供應商報價 Excel，
計算材料成本變化對成品成本的影響，並標記需人工確認的例外。

本工具不取代 ERP；它是 ERP／Excel 旁的受控試算與審核工具。

> **目前狀態：僅完成資料整理（規格文件與 Excel 範例／測試資料的目錄結構），尚未開發任何應用程式。**
> 目前儲存庫中沒有 Python 程式、相依套件、UI、Docker 或 CI 設定。

## 目錄結構

```text
README.md
docs/
  IMPLEMENTATION_SPEC.md
samples/
  sample_bom.xlsx
  sample_price_increase.xlsx
tests/
  fixtures/
    expected_result_reference.xlsx
    test_bom_edge_cases.xlsx
    test_price_edge_cases.xlsx
```

| 檔案 | 用途 |
|---|---|
| `docs/IMPLEMENTATION_SPEC.md` | **產品規格來源（single source of truth）**：產品定位、輸入資料規則、成本計算定義、驗收數值與開發分階段建議。實作與規格衝突時，以此文件為準。 |
| `samples/sample_bom.xlsx` | 正常案例 BOM（工作表 `BOM`，另含 `ProductCost`、`欄位字典`）：6 種成品、27 種材料、40 筆明細。 |
| `samples/sample_price_increase.xlsx` | 正常案例供應商調價（工作表 `PriceIncrease`）：11 筆有效調價與 1 筆不在 BOM 的 M-999 報價。 |
| `tests/fixtures/expected_result_reference.xlsx` | **驗收參考結果**（`Summary`、`Cost Impact`、`Exceptions`、`Line Audit`、`Expected Numbers`、`Acceptance Cases`）。 |
| `tests/fixtures/test_bom_edge_cases.xlsx` | BOM 邊界案例：未核准 BOM、每批基準產量非 1、未展開半成品等。 |
| `tests/fixtures/test_price_edge_cases.xlsx` | 報價邊界案例：重複料號、錯單位、空價、零價、文字價格、USD、每百件報價、未生效報價、錯供應商等。 |

所有 Excel 皆為合成測試資料，不含真實客戶資料。

### 關於驗收參考檔

`tests/fixtures/expected_result_reference.xlsx` 是驗收基準。
**未來不得為了讓測試通過而修改此檔案。** 若測試與此檔不符，應修正程式；
若確認是參考檔本身有誤，須另開獨立變更並說明依據，不可與功能實作混在一起。

### 新舊路徑對照

規格文件 `docs/IMPLEMENTATION_SPEC.md` 以檔名（不含目錄）提及各工作簿，本次整理未修改規格內容。
這些檔案原本位於 `supplier_price_impact_erp_starter_pack/`，對照如下：

| 原路徑 | 新路徑 |
|---|---|
| `supplier_price_impact_erp_starter_pack/IMPLEMENTATION_SPEC.md` | `docs/IMPLEMENTATION_SPEC.md` |
| `supplier_price_impact_erp_starter_pack/sample_bom.xlsx` | `samples/sample_bom.xlsx` |
| `supplier_price_impact_erp_starter_pack/sample_price_increase.xlsx` | `samples/sample_price_increase.xlsx` |
| `supplier_price_impact_erp_starter_pack/expected_result_reference.xlsx` | `tests/fixtures/expected_result_reference.xlsx` |
| `supplier_price_impact_erp_starter_pack/test_bom_edge_cases.xlsx` | `tests/fixtures/test_bom_edge_cases.xlsx` |
| `supplier_price_impact_erp_starter_pack/test_price_edge_cases.xlsx` | `tests/fixtures/test_price_edge_cases.xlsx` |

## 驗收基準

以 2026-12-01 作為調價情境日。

系統必須能根據：
- `samples/sample_bom.xlsx`
- `samples/sample_price_increase.xlsx`

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
- `tests/fixtures/test_bom_edge_cases.xlsx`
- `tests/fixtures/test_price_edge_cases.xlsx`
- `tests/fixtures/expected_result_reference.xlsx`

缺少人工、製造費用或其他完整成本資料時，系統只能輸出材料成本影響，
不得宣稱或計算完整成品毛利率。
