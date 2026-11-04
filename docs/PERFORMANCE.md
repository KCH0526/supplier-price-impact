# 效能與品質驗證（PR #14）

全部使用**合成資料**。重新執行：

```bash
python benchmarks/run_benchmark.py 1000 10000 20000 50000
```

## 1. 執行環境

| 項目 | 值 |
|---|---|
| Python | 3.11.18 |
| 平台 | Linux 6.18（x86_64，glibc 2.39），雲端開發容器 |
| CPU | 4 核 |
| 日期 | 2026-11-04 |

## 2. 測試資料

N 為 BOM 行數。每個成品 10 行，所以成品數為 N/10；供應商調價 N/2 列，客戶報價 N/10 列。
所有資料都完整、有效（0 個例外），目的是測量正常流程的耗時。

## 3. 結果（秒；記憶體為該規模單獨執行時的峰值 RSS）

| BOM 列數 | 輸入檔大小 | 讀取 | 配對 | 計算 | 報價風險 | 匯出 | 合計 | 峰值記憶體 | 報告大小 | 結果 |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| 1,000 | 0.06 MB | 0.20 | 0.04 | 0.02 | 0.01 | 0.65 | 0.92 | 124 MB | 0.09 MB | 成功 |
| 10,000 | 0.46 MB | 1.51 | 0.22 | 0.11 | 0.04 | 6.54 | 8.42 | 229 MB | 0.81 MB | 成功 |
| 20,000 | 0.91 MB | 3.09 | 0.54 | 0.25 | 0.07 | 12.66 | 16.60 | 345 MB | 1.62 MB | 成功 |
| 50,000 | 2.27 MB | 7.48 | 1.37 | 0.61 | 0.20 | 33.02 | 42.69 | 688 MB | 4.04 MB | 成功 |

- 各階段耗時都和資料量成正比：50,000 列約為 1,000 列的 46 倍，**沒有平方級的效能退化**。
- 匯出 Excel 佔總時間的 75～80%。
- 50,000 列是每個工作表的上限；超過會被阻擋（已有測試）。

### 瀏覽器實測（50,000 列）

在本機 Streamlit 以 Chromium 上傳三份 50,000 列等級的檔案，按下按鈕後：

- **49 秒**完成，下載的報告完整：Line Audit 50,000 列、5,000 個成品、5,000 筆報價。
- 處理期間畫面會顯示「報告產生中…」提示。

### 歷史報價記憶庫（PR #20，2026-11-04）

`python benchmarks/run_quote_memory_benchmark.py 25000`：2 個檔案、各 25,000 列，共 50,000 列，涵蓋 500 個成品。

| 匯入 | 查詢 | 建議 | 報告 | 峰值記憶體 | 結果 |
|---:|---:|---:|---:|---:|---|
| 6.41 秒 | 0.40 秒 | 0.01 秒 | 0.09 秒 | 271 MB | 成功；50,000 筆全部匯入；選入 100 筆可比較報價 |

### 報價工作台（PR #26）

數量階梯最多 20 個數量，每個數量做一次歷史查詢；在 50,000 筆歷史報價下，單次歷史查詢約 0.4 秒（見上表），因此 20 個數量約需 8 秒。沒有另外做大型基準測試。

## 4. 本 PR 發現並修正的問題

| 問題 | 嚴重度 | 處理方式 |
|---|---|---|
| 大檔案處理需要 40～50 秒，但按下按鈕後畫面沒有任何提示，使用者可能以為當機而重複點擊 | 低 | 加上處理中提示。**沒有**為了效能大幅重構匯出程式 |

## 5. 部署建議

- 記憶體：50,000 列時單一使用者約需 0.7 GB。建議主機至少 2 GB，並避免多人同時處理大檔。
- 資料量很大時，先在 ERP 篩選出受影響的成品或工廠，可以大幅縮短時間。

## 6. 品質檢查對照（每一項對應的自動化測試）

| 檢查項目 | 測試位置 |
|---|---|
| 大檔案、資料列上限 | `tests/test_security.py`（大小、列數）、本文件第 3 節 |
| XLSX 異常結構（解壓縮炸彈、截斷、損毀 XML、損毀儲存格） | `tests/test_security.py`、`tests/test_release_gate.py` |
| Excel 公式注入 | `tests/test_security.py`、`tests/test_report.py`、`tests/test_adversarial.py`、`tests/test_field_mapper.py` |
| 前導零（讀取到匯出） | `tests/test_reader.py`、`tests/test_quote_reader.py`、`tests/test_quality.py` |
| 空白識別碼 | `tests/test_validation.py`、`tests/test_quote_validation.py` |
| 重複鍵（表頭、報價、客戶報價單號＋行號） | `tests/test_reader.py`、`tests/test_matcher.py`、`tests/test_quote_validation.py` |
| 錯誤單位、錯誤幣別、每百件報價 | `tests/test_matcher.py`、`tests/test_quote_validation.py` |
| 不完整成本（不當成 0） | `tests/test_calculator.py`、`tests/test_quote_risk.py`、`tests/test_release_gate.py` |
| 日期區間（包含首尾日） | `tests/test_matcher.py`、`tests/test_quote_risk.py` |
| 報價狀態 | `tests/test_matcher.py`、`tests/test_quote_validation.py` |
| 小數精度（Decimal） | `tests/test_quality.py`、`tests/test_calculator.py` |
| 底價無條件進位 | `tests/test_quote_risk.py`、`tests/test_report.py` |
| 大量資料效能退化 | `tests/test_quote_risk.py`（線性檢查）、本文件第 3 節 |

## 7. 尚未驗證

- 在客戶的實際硬體上執行（例如 Windows 筆電或內網伺服器）。
- 多位使用者同時上傳大檔。
- 真實 ERP 資料的列數分布與欄位雜訊。
