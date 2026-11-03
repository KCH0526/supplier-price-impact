# Supplier Price Impact

供應商漲價影響試算器。

上傳標準化 BOM／成本匯出 Excel 與供應商報價 Excel，
計算材料成本變化對成品成本的影響，並標記需人工確認的例外。

本工具不取代 ERP；它是 ERP／Excel 旁的受控試算與審核工具。
產品規格來源為 [`docs/IMPLEMENTATION_SPEC.md`](docs/IMPLEMENTATION_SPEC.md)。

> **目前狀態：開發中。** 僅完成 Excel 讀取與基本輸入驗證，
> 尚無成本計算、使用者介面或報表輸出，還不能拿來做實際試算。

## 目前已完成的功能

- `core/reader.py`：讀取 `BOM` 與 `PriceIncrease` 工作表
  - 支援檔案路徑、`bytes` 及二進位檔案物件（例如上傳檔）
  - 檢查必要工作表與必填欄位；依表頭名稱讀取，不依欄位順序
  - 識別碼欄位一律為文字，文字料號的前導零會保留
  - 空白儲存格為 `None`，不會變成 `NaN` 或字串 `"nan"`
  - 每筆資料保留 Excel 列號（`excel_row`，表頭為第 1 列）；略過整列空白
  - 擴充欄位（工廠代碼、供應商代碼等）原樣保留
- `core/validation.py`：逐列基本驗證
  - 識別碼、單位、幣別不可空白；數字與日期格式檢查
  - 每筆問題記錄 工作表、Excel 列號、欄位、原因、原始值
  - 區分 **阻擋**（`error`）與 **警告**（`warning`）

### 驗證規則摘要

| 工作表 | 欄位 | 規則 | 嚴重度 |
|---|---|---|---|
| BOM | 成品編號、子件料號、單位 | 不可空白 | 阻擋 |
| BOM | 成品名稱、子件名稱 | 不可空白（僅供顯示） | 警告 |
| BOM | 用量 | 有限數字且 > 0 | 阻擋 |
| BOM | 原單價 | 有限數字且 ≥ 0（0 為合法值） | 阻擋 |
| BOM | 生效起日、生效迄日（選填） | 有值時須為有效日期 | 阻擋 |
| BOM | BOM基準產量、原單價計價數量（選填） | 有值時須為數字且 > 0 | 阻擋 |
| BOM | 同一成品、子件料號、行號完全相同 | 可能重複輸入 | 警告 |
| PriceIncrease | 子件料號、單位、幣別 | 不可空白 | 阻擋 |
| PriceIncrease | 子件名稱 | 不可空白（僅供顯示） | 警告 |
| PriceIncrease | 新單價 | 有限數字且 > 0；空白、0、負數、文字皆拒絕 | 阻擋 |
| PriceIncrease | 生效日 | 必填，須為 Excel 日期或 `YYYY-MM-DD` 文字 | 阻擋 |
| PriceIncrease | 價格迄日（選填）、計價數量（選填） | 有效日期／數字 > 0 | 阻擋 |

同一子件料號出現在多個成品，或在同一成品的不同行號出現，都是合法 BOM，不會被判為錯誤。

## 環境需求

- Python 3.11 以上（規格指定 3.11；本次在 3.13 執行測試）
- 依賴：`pandas`、`openpyxl`、`pytest`（見 `requirements.txt`）

### 安裝

```bash
python -m pip install -r requirements.txt
```

### 執行測試

在儲存庫根目錄執行：

```bash
python -m pytest -q
```

### 程式使用範例

```python
from core.reader import read_bom
from core.validation import validate_bom, has_blocking

result = read_bom("samples/sample_bom.xlsx")
issues = result.issues or validate_bom(result.data)
if has_blocking(issues):
    for issue in issues:
        print(issue.to_dict())
```

## Excel 必填欄位

欄位名稱位於第 1 列，資料自第 2 列起。其他欄位可以存在，會原樣保留。

| 工作表 | 必填欄位 |
|---|---|
| `BOM` | 成品編號、成品名稱、子件料號、子件名稱、單位、用量、原單價 |
| `PriceIncrease` | 子件料號、子件名稱、單位、幣別、新單價、生效日 |

## 目錄結構

```text
README.md
requirements.txt
core/
  reader.py                 Excel 讀取
  validation.py             基本輸入驗證
docs/
  IMPLEMENTATION_SPEC.md    產品規格來源
samples/
  sample_bom.xlsx           正常案例 BOM
  sample_price_increase.xlsx  正常案例供應商調價
tests/
  test_reader.py
  test_validation.py
  fixtures/
    expected_result_reference.xlsx  驗收參考結果
    test_bom_edge_cases.xlsx        BOM 邊界案例
    test_price_edge_cases.xlsx      報價邊界案例
```

`tests/fixtures/expected_result_reference.xlsx` 是驗收基準。
**未來不得為了讓測試通過而修改此檔案。** 若確認參考檔本身有誤，須另開獨立變更並說明依據。

所有 Excel 皆為合成測試資料，不含真實客戶資料。

規格文件只以檔名提及各工作簿；這些檔案原本都位於 `supplier_price_impact_erp_starter_pack/`，
現已依上方目錄樹分別移至 `docs/`、`samples/`、`tests/fixtures/`，內容未變更。

## 尚未完成的功能

以下功能**尚未開發**：

- 報價選擇：試算基準日、生效日／價格迄日、報價狀態、重複報價與一料多供應商的判斷
- 一致性檢核：單位、幣別、計價數量、供應商、BOM 核准狀態、基準產量、未展開半成品
- 未匹配報價（例如 M-999）的例外處理
- 材料成本與完整成本試算、月成本增額
- Streamlit 使用者介面
- Excel 結果報告下載
- Docker 部署

## 驗收基準

以 2026-12-01 作為調價情境日。

系統必須能根據：
- `samples/sample_bom.xlsx`
- `samples/sample_price_increase.xlsx`

產生與以下參考結果一致的成本影響（含 `ProductCost` 的模擬人工與製造費用）：

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

<!-- 後續 UI PR 將補充：使用者操作說明、產品優勢、台灣 ERP 使用案例、FAQ -->
