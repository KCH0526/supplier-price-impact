# 文件與檔案盤點

盤點日期：2026-11-04　｜　基準：main `36ab3a26d7e9cf5645c492831655862525e23491`
方法：對每個 `docs/`、`demo/`、`benchmarks/`、`tools/`、`web_src/` 檔案，搜尋其他程式、測試、文件與 CI 是否引用。

**結論：沒有找到可以安全刪除的檔案。** 每一個檔案至少被另一個程式、測試或文件引用；`demo/*.xlsx` 有測試比對「提交的檔案與重新產生的結果相同」，屬於驗收依據；`web/` 雖由 `web_src/` 產生，但有獨立的網站測試直接檢查 `web/` 的內容，所以也不是可以直接刪除的多餘輸出。因此本次只做整合與搬移，沒有刪除檔案。

## 1. 正式產品必要檔案（保留）
| 路徑 | 用途 |
|---|---|
| `app.py`、`pages/` | Streamlit 介面：毛利風險報告、Excel 欄位對應、歷史報價與建議報價、報價工作台、案件工作台 |
| `core/` | 讀取、驗證、配對、成本計算、報價風險、歷史報價、批次成本、數量階梯、版本比較、客戶草稿、RFQ、案件資料庫、實際成本回饋、報告產生 |
| `requirements.txt`、`requirements-lock.txt` | 直接依賴與完整鎖定版本 |
| `start_windows.bat`、`start_macos.command`、`tools/check_env.py` | 啟動與環境檢查 |
| `.streamlit/config.toml` | 只綁定本機、關閉使用統計、上傳大小限制 |
| `Dockerfile`、`docker-compose.yml`、`.dockerignore` | 容器化執行（只發布在 127.0.0.1） |
| `.gitignore`、`.gitattributes` | 排除資料庫與備份；固定啟動腳本換行格式 |

## 2. 自動化測試與驗收資料（保留，不可修改驗收答案）
| 路徑 | 用途 |
|---|---|
| `tests/`（含 `tests/fixtures/`） | 全部自動化測試與原始驗收基準檔 |
| `samples/` | 合成範例：成本、調價、未結報價、ERP 匯出、欄位對應、歷史報價、批次成本、RFQ |
| `demo/build_*.py`、`demo/*.xlsx` | 範例報告；測試比對提交的檔案與重新產生的結果相同 |
| `benchmarks/` | 效能基準（`run_benchmark.py` 由測試執行；`run_quote_memory_benchmark.py` 由 `docs/PERFORMANCE.md` 引用） |
| `tools/ci_report.py`、`.github/workflows/ci.yml` | 三平台 CI 與 0 failed／0 skipped 規則 |

## 3. 使用者操作文件
| 文件 | 讀者 |
|---|---|
| `README.md` | 評估導入的企業：產品介紹、功能、安裝、文件索引 |
| `docs/USER_GUIDE.md` | 使用者：完整操作手冊（原 README 的詳細內容，章節編號不變） |
| `docs/FIRST_TIME_GUIDE.md`、`docs/FIRST_USE_CHECKLIST.md` | 第一次使用 |
| `docs/LOCAL_DEPLOYMENT.md`、`docs/DEPLOYMENT_CHECKLIST.md` | 安裝、部署、備份還原、故障排除 |
| `docs/LIMITATIONS.md` | 支援範圍與限制 |
| `docs/CUSTOMER_ONBOARDING.md`、`docs/delivery/` | 導入流程、資料需求、簽核與驗收表 |
| `docs/DEMO_SCRIPT.md`、`docs/ONE_PAGER.md`、`docs/SERVICE_SCOPE.md`、`docs/images/`、`docs/media/` | 展示與介紹（截圖與影片都是真實系統畫面，使用合成資料） |

## 4. 內部開發與決策紀錄（保留，不屬於使用者文件）
| 文件 | 說明 |
|---|---|
| `docs/WORK_LOG.md` | 開發紀錄、PR 歷程、環境備忘 |
| `docs/RELEASE_GATE.md`、`docs/ENTERPRISE_RC_REPORT.md`、`docs/FINAL_DELIVERY_REPORT.md`、`docs/FINAL_QUALITY_REVIEW.md` | 驗收證據與品質審查 |
| `docs/IMPLEMENTATION_SPEC.md` | 原始驗收規格（受保護，不可修改） |
| `docs/COMMERCIAL_QUOTING_SPEC.md`、`docs/HISTORICAL_QUOTE_PRODUCT_SPEC.md`、`docs/PRODUCTION_QUOTING_ROADMAP.md` | 功能規格與路線圖 |
| `docs/PERFORMANCE.md` | 效能實測紀錄 |
| `docs/PRODUCT_DECISION.md`、`docs/GO_TO_MARKET.md`、`docs/PUBLIC_LAUNCH_DECISION.md` | 產品與商業化決策紀錄 |

## 5. 公開網站原始碼（保留，目前不在交付範圍）
| 路徑 | 說明 |
|---|---|
| `web_src/` | 靜態網站與示範內容的產生程式 |
| `web/` | 由 `web_src/` 產生的靜態網站；**尚未部署，本次也不部署** |
| `docs/launch/` | 網站上線前的檢查與草稿文件 |

決定：保留作為未來用途。`tests/test_web_site.py`、`tests/test_web_demo.py` 直接檢查 `web/`：沒有追蹤碼、廣告、上傳表單、對外資源，連結有效，示範頁不含內部資料。注意：目前**沒有**測試比對 `web/` 與 `web_src/` 重新產生的結果是否一致；修改 `web_src/` 後須手動重新產生。

## 6. 本次整合與搬移
| 變更 | 理由 |
|---|---|
| 原 `README.md` 搬到 `docs/USER_GUIDE.md`（章節編號不變，相對連結已調整） | README 改為產品介紹，詳細操作留在手冊；既有的「第 N 節」引用改指向手冊 |
| 新 `README.md` | 以產品文件方式介紹六大模組、工作流程、安裝與文件索引 |
| `FIRST_TIME_GUIDE`、`CUSTOMER_ONBOARDING`、`delivery/10`、`delivery/11`、`launch/ENTERPRISE_DEPLOYMENT` 的「README 第 N 節」 | 改為「使用手冊第 N 節」 |
| 舊 README 測試（主題涵蓋）改為檢查 `docs/USER_GUIDE.md` | 內容搬移，檢查的主題與數字不變 |

## 7. 待確認（不刪除）
| 檔案 | 狀況 | 建議 |
|---|---|---|
| `docs/PRODUCT_DECISION.md`、`docs/GO_TO_MARKET.md`、`docs/PUBLIC_LAUNCH_DECISION.md` | 只被其他內部文件引用，屬於歷史決策 | 由專案負責人決定是否改放到封存資料夾 |
| `docs/launch/`、`web/`、`web_src/` | 公開網站目前不在交付範圍 | 若確定不做網站，可另開 PR 封存；刪除前需一併移除相關測試 |
| `benchmarks/run_quote_memory_benchmark.py` | 只被 `docs/PERFORMANCE.md` 引用，沒有測試執行 | 保留作為效能重測工具 |
| `docs/media/demo_walkthrough.webm`（約 1.3 MB） | 早期錄製，未包含報價工作台與案件工作台 | 之後可重新錄製 |
