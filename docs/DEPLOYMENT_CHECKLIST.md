# 部署驗收清單（Deployment Checklist）

本文件記錄**實際執行過**的驗收與**尚未驗證**的項目。
每次正式交付客戶前，請在客戶的實際環境重新執行一次並簽核。

## 1. Python 3.11 啟動

```bash
python3.11 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements-lock.txt   # 固定版本
python -m pytest -q -rs          # 必須 0 failed、0 skipped
streamlit run app.py --server.address=127.0.0.1
```

## 2. Docker 啟動

```bash
docker compose up --build
# 瀏覽器開啟 http://127.0.0.1:8501
```

- 映像以 `python:3.11-slim` 為基底，網頁服務以非 root 使用者（uid 10001）執行。
- `docker-compose.yml` 只把服務發布在 `127.0.0.1:8501`。
  **不要**改成 `8501:8501` 或 `0.0.0.0:8501:8501`，否則同網段任何人都能連線。
- 若手動使用 `docker run`，請寫成 `-p 127.0.0.1:8501:8501`。
- 公司網路若有 SSL 檢查 proxy（pip 出現 `CERTIFICATE_VERIFY_FAILED`），請向 IT 取得公司 CA 憑證，
  並以 build secret 傳入。憑證只在安裝套件時掛載，**不會**寫進映像：

```bash
docker build --secret id=corp_ca,src=/path/to/company-ca.crt -t supplier-quote-margin-guard .
docker run --rm -p 127.0.0.1:8501:8501 supplier-quote-margin-guard
```

## 3. 上傳與報告驗證

1. 上傳 `samples/sample_bom.xlsx`、`samples/sample_price_increase.xlsx`、`samples/sample_open_quotes.xlsx`。
2. 試算基準日 2026-12-01、最低毛利率 15%，按「產生毛利風險報告」。
3. 下載 `result.xlsx`，確認：
   - 工作表：Summary、Cost Impact、Exceptions、Line Audit、Quote Risk、Quote Exceptions
   - Quote Risk：需人工覆核 3 筆（P-1003、P-1001、P-1005），P-1001 最低單價 1,026.12
   - 預估每月總成本增加：61,597.00
   - 6 款成品成本與 `tests/fixtures/expected_result_reference.xlsx` 的 Expected Numbers 一致
   - Line Audit 40 列，與參考檔逐列一致
   - Exceptions 僅 M-999「漲價料號未匹配」（非阻擋）

## 4. 網路與資料安全設定

| 項目 | 設定 |
|---|---|
| Streamlit 使用統計 | `.streamlit/config.toml`：`gatherUsageStats = false` |
| 啟動時查詢公開 IP（checkip.amazonaws.com） | 以 `browser.serverAddress = "localhost"` 關閉 |
| 上傳大小上限 | Streamlit `maxUploadSize = 20`（MB）；讀取層同為 20 MB |
| 解壓縮炸彈 | 解壓後總量上限 200 MB；單一項目 >1 MB 且壓縮比 >200 即拒絕 |
| 資料列上限 | 每工作表 50,000 列 |
| Streamlit「Deploy」按鈕（導向公開雲端） | 以 `client.toolbarMode = "minimal"` 隱藏 |
| 上傳檔保存 | 只在記憶體處理，不寫入磁碟；容器內 `/app` 對執行者不可寫 |
| Excel 公式注入 | 匯出時以 `=`、`+`、`-`、`@`、Tab、換行開頭的文字一律加前置 `'` |
| 上傳檔中的公式 | 以 `data_only=True` 讀取，不執行公式 |

## 5. 企業內網部署注意事項

- 只部署在本機或私有內網；不要把真實 BOM、成本或報價上傳到公開 Demo 主機。
- 若需多人使用，請放在公司反向代理（HTTPS）之後，並由公司既有的網路存取控制限制來源 IP。
  本工具**沒有**登入或權限系統。
- 下載的 `result.xlsx` 含成本與毛利資訊，請依公司文件保密規定保存。
- 伺服器重啟即清除所有工作階段資料；工具不保留歷史紀錄。

## 6. 實際驗收紀錄

| 日期 | 項目 | 環境 | 結果 |
|---|---|---|---|
| 2026-11-03 | 完整 pytest | Python 3.11.18（venv），含 Streamlit 1.66.1 | 137 passed、0 skipped |
| 2026-11-03 | 瀏覽器實測上傳→產生報告→下載 | 本機 Streamlit，Chromium（Playwright） | 成功；6 款成品、40 列 Line Audit、61,597 全部吻合；匯出檔 0 個公式 |
| 2026-11-03 | 瀏覽器端外部請求 | 同上，攔截所有非 127.0.0.1 請求 | 0 筆 |
| 2026-11-03 | 伺服器端對外連線 | 將 HTTP(S) proxy 指向本機記錄器後跑完整流程 | 0 筆（伺服器綁 127.0.0.1 時） |
| 2026-11-03 | Docker build 與啟動 | Docker 29.9.2；build 時另加 proxy CA（雲端開發環境限制，見下） | 成功；容器內 pytest 137 passed；以 uid 10001 執行；只綁 127.0.0.1 |
| 2026-11-03 | 容器內瀏覽器實測 | 同上 | 成功；61,597、40 列；容器內未留下上傳的 xlsx |
| 2026-11-03 | 啟動時外部 IP 查詢 | 容器（綁 0.0.0.0） | 修正前會查 checkip.amazonaws.com；修正後不再查詢 |
| 2026-11-03 | 三檔流程瀏覽器實測（BOM＋調價＋OpenQuotes） | Python 3.11.18，本機 Streamlit，Chromium | 成功；6 個工作表；需人工覆核 3 筆；情境合計 6,480.50；月成本 61,597；瀏覽器端外部請求 0 筆 |
| 2026-11-03 | 「Deploy」按鈕 | 同上 | 已隱藏（頁面上數量 0） |
| 2026-11-03 | 最終回歸：Docker 重建＋容器內 pytest＋三檔瀏覽器流程 | Docker 29.9.2，映像 python:3.11-slim（另加 proxy CA，見下） | 容器內 234 passed；案例 A 16.34%／12.78%／1,026.12／1,780／需人工覆核；61,597；Line Audit 40 列；匯出檔 0 個公式；容器內沒有寫入任何 xlsx；啟動時未查詢外部 IP |
| 2026-11-04 | 完整 pytest（PR #11） | Python 3.11.18（venv），Streamlit 1.66.1 | 243 passed、0 failed、0 skipped |
| 2026-11-04 | **repo 原始 Dockerfile** build | Docker 29.9.2；以 `--secret id=corp_ca` 傳入 proxy CA（不寫入映像） | 成功；映像內無 `/run/secrets`、`/app` 內無憑證；uid 10001 |
| 2026-11-04 | 容器內三檔瀏覽器流程 | 同上，Chromium | 6 個工作表；6 款成品 0 差異；Line Audit 40 列一致；61,597；需人工覆核 3／尚符合 4／不納入 1；情境合計 6,480.50；案例 A 16.34%／12.78%／1,026.12；0 個公式；瀏覽器外部請求 0 筆；容器內未寫入 xlsx；啟動未查詢外部 IP |
| 2026-11-04 | 上傳大小上限 | 同上，上傳 22 MB 檔案 | 前端拒絕：「File must be 20.0MB or smaller」 |
| 2026-11-04 | 損毀 xlsx（數值儲存格內為文字） | Python 3.11.18 | 修正前 `read_bom` 拋出 `ValueError`（畫面會出現錯誤堆疊）；修正後成為阻擋例外 |

Docker 驗證說明：

- 2026-11-03 的紀錄是用一份多了「信任 proxy CA」步驟的 Dockerfile **副本**建置的。
- 自 2026-11-04（PR #11）起，repo 的 Dockerfile 支援以 build secret 傳入 CA，所以改為直接用 **repo 原始 Dockerfile** 建置驗證。
- 沒有傳入 secret 時，建置行為與一般 `pip install` 相同；但這種情況下，一般網路的建置在本開發環境無法重現（見第 7 節）。

## 7. 尚未實際驗證

- 在客戶公司電腦或內網伺服器（Windows／macOS Docker Desktop）上的實際啟動。
- 使用 repo 原始 `Dockerfile`、**不傳入 CA**、在沒有 SSL 檢查 proxy 的一般網路建置（本開發環境一定經過 proxy，無法重現）。
- 反向代理／HTTPS 配置。
- 真實企業 ERP 匯出檔（目前只有合成資料）。
- 效能已在開發環境實測（見 `docs/PERFORMANCE.md`）。客戶硬體上的效能仍未驗證，50,000 列約需 0.7 GB 記憶體。
