# 工作紀錄（給下一個開發 session）

每完成一個 PR 就更新本檔。新的 session 請先讀本檔，再從最新 `main` 建立分支繼續。

## 目前進度

| PR | 內容 | 狀態 |
|---|---|---|
| #1～#5 | 目錄整理、讀取驗證、配對、成本計算、Streamlit、Docker | 已合併 |
| #6 | Python 3.11／Docker／安全驗收、CI | 已合併（main `70ee1bb`） |
| #7 | OpenQuotes 讀取與驗證、產品決策紀錄 | 已合併（main `c10b673`） |
| #8 | 毛利風險覆核引擎 `core/quote_risk.py` | 已合併（main `031e723`） |
| #9 | 三檔 Streamlit、Quote Risk 報告、README、ONBOARDING、GO_TO_MARKET | 已合併（main `522090c`） |
| #10 | 對抗測試、最終 Docker 回歸、交付紀錄 | 已合併（main `622f3bb`） |
| #11 | 正式交付驗收：修正損毀 xlsx 造成的錯誤、Dockerfile 支援企業 CA、RELEASE_GATE | 已合併（main `62a358b`） |
| #12 | Excel 欄位對應器（`core/field_mapper.py`、`pages/1_Excel_欄位對應.py`） | 已合併（main `2dcd22b`） |
| #13 | 示範與銷售素材（demo/、截圖、影片、DEMO_SCRIPT、FIRST_TIME_GUIDE、ONE_PAGER、SERVICE_SCOPE） | 已合併（main `cff32c5`） |
| #14 | 品質與效能（benchmarks/、PERFORMANCE.md、處理中提示） | 已合併（main `1d99b70`） |
| #15 | 客戶交付工具包（`docs/delivery/` 10 份文件） | 已合併（main `cbb4564`） |
| #16 | 歷史報價匯入與標準化（`core/historical_quotes.py`、規格 `docs/HISTORICAL_QUOTE_PRODUCT_SPEC.md`） | 已合併（main `3735f7a`） |
| #17 | 歷史報價查詢與相似案件檢索（`core/quote_search.py`） | 已合併（main `b446ca6`） |
| #18 | 建議報價與異常警示（`core/quote_advisor.py`） | 已合併（main `0a1af12`） |
| #19 | 歷史報價頁面、覆核報告、README | 已合併（main `f7bbc56`） |
| #20 | 對抗測試、效能、Docker 端對端、限制清單、首次客戶導入驗收表 | 已合併（main `9e7eb8b`） |
| #21 | 安全的客戶報價草稿（`core/customer_draft.py`；規格 `docs/COMMERCIAL_QUOTING_SPEC.md`） | 已合併（main `ad9b298`） |
| #22 | 批次成本模型（`core/batch_cost.py`，兩種互斥模式） | 已合併（main `0dcb3a1`） |
| #23 | 數量階梯與最低報價（`core/quantity_tiers.py`） | 已合併（main `e68f5a9`） |
| #24 | 報價版本比較（`core/quote_versions.py`） | 已合併（main `aeb6220`） |
| #25 | 報價工作台頁面（`pages/3_報價工作台.py`）、內部報告、文件 | 已合併（main `51e18c7`）※ 合併時 CI 尚在執行，事後確認 CI 通過（見下方紀錄） |
| #26 | 最終安全、品質及交付驗收（對抗測試、Docker、試用工具包） | 已合併（main `412547b`） |
| #27 | 報告類型明確化（成本影響／客戶報價風險）、草稿與正式報價單區分、流程與文件整理 | 已合併（main `097fdfa`） |
| #28 | 公開入口與商業化決策（`docs/PUBLIC_LAUNCH_DECISION.md`） | 已合併（main `6723618`） |
| #29 | 公開繁體中文靜態網站（`web/`、`web_src/`）與 4 個瀏覽器內計算器 | 已合併（main `60faf9f`） |
| #30 | 公開合成資料 Demo（`web_src/demo_content.py` 預先產生 `web/demo/`，無上傳） | 已合併（main `b05f699`） |
| #31 | 商業化與上線驗收文件（`docs/launch/` 13 份） | 已合併（main `8434626`） |
| #32 | 本機案件資料保存層（`core/case_store.py`）與路線圖（`docs/PRODUCTION_QUOTING_ROADMAP.md`） | 進行中（分支 `claude/local-case-store`） |
| #33 | 客戶詢價 RFQ 匯入與案件狀態流程 | 未開始 |
| #34 | 成交與實際成本回饋、差異分析 | 未開始 |
| #35 | 案件工作台頁面與稽核報告 | 未開始 |
| #36 | 候選版本驗收與文件 | 未開始 |

技術 MVP 已完成，以合成資料驗收。交付閘門見 `docs/RELEASE_GATE.md`。商業驗證尚未開始（見 `docs/GO_TO_MARKET.md` 第 9 節）。

## 常用指令

```bash
python3.11 -m venv .venv && . .venv/bin/activate
python -m pip install -r requirements.txt
python -m pytest -q -rs     # 必須 0 failed、0 skipped
streamlit run app.py --server.address=127.0.0.1
```

## 不可修改（驗收資料）

- `docs/IMPLEMENTATION_SPEC.md`
- `samples/sample_bom.xlsx`、`samples/sample_price_increase.xlsx`、`samples/sample_open_quotes.xlsx`
- `tests/fixtures/` 內全部檔案

## 編號說明

使用者在任務中以「PR #27～#30」稱呼公開入口的四個階段；因 #27 已用於可靠性強化，實際編號為 #28～#31。

## 公開入口現況（PR #28～#31）

- `web/` 公開靜態網站與 `web/demo/` 合成資料 Demo 已完成，**尚未部署**。
- 部署、網域、託管、廣告、金流、聯絡方式都需要使用者決定並授權，見 `docs/launch/USER_DECISIONS.md`。

## 分支保護（需要 repository 管理者操作）

本開發環境的 GitHub 工具無法讀取或修改分支保護，`gh` CLI 也只允許用於搜尋，所以 PR #27 **沒有**設定分支保護。請在 GitHub 上操作：

1. 進入 repository → **Settings** → **Rules → Rulesets**（或 **Branches → Add branch protection rule**）。
2. 目標分支：`main`。
3. 勾選 **Require a pull request before merging**。
4. 勾選 **Require status checks to pass**，加入必要檢查 **`test`**（workflow `CI` 中的 job 名稱）；建議同時勾選 **Require branches to be up to date before merging**。
5. 勾選 **Block force pushes**（Rulesets）或保持 **Allow force pushes** 未勾選（傳統分支保護）。
6. 保持 **Allow deletions** 未勾選。

設定完成後，即使有人在 CI 完成前送出合併，GitHub 也會拒絕。

## 流程異常紀錄

- PR #25：查詢 CI 與合併的指令同時送出，導致在 CI 完成前就合併。事後確認該次 CI（run 41785311806）結果為 success。
  main 沒有設定「必要 status check」，所以 GitHub 沒有擋下。**建議在 GitHub 的分支保護中，把 CI 的 test 設為必要檢查。**

## PR 連結

#6～#26：https://github.com/KCH0526/supplier-price-impact/pull/6 至 /pull/26（編號依序）。

## 已知限制（截至 PR #20；完整清單見 `docs/LIMITATIONS.md`）

- 只用合成資料驗收；沒有任何真實客戶資料、訪談或成交紀錄。
- 只支援單階 BOM、單一工廠與版本、TWD、每件計價；欄位對應不支援合併欄位或常數欄位。
- 一般網路下、不傳入 CA 的原始 Dockerfile 建置，以及 Windows／macOS Docker Desktop，都尚未驗證。
- 匯出 Excel 是最慢的環節（50,000 列約 33 秒）。
- 法律相關文件都是草案，必須經專業人士審閱。

## 下一步建議（依價值排序）

1. 在自己的 Windows／macOS 電腦執行 `docker compose up --build`，用三份範例與欄位對應範例各走一次（見 `docs/RELEASE_GATE.md` 第 3 節）。
2. 依 `docs/GO_TO_MARKET.md` 進行真實訪談（目標 10 位）。這一步需要真人執行，AI 不能代勞或虛構結果。
3. 取得第一份經授權、已去識別化的真實資料，依 `docs/delivery/` 的流程導入，記錄欄位對應實際花費的時間。
4. 依真實資料的需要再決定開發什麼（例如報價狀態對照、欄位別名）；不要先開發多階 BOM 或匯率功能。

## 環境備忘

- 雲端開發環境的 Docker build：先啟動 `dockerd`，再執行
  `docker buildx build --network host --secret id=corp_ca,src=/root/.ccr/ca-bundle.crt -t spi --load .`
- 額度：使用者回報剩餘 US$86（2026-11-04 PR #11 開始時）、US$75（PR #16 開始時）；US$64（PR #21 開始時）；US$35（PR #32 開始時）；各階段實際花費未知。session 內無法讀取實際用量，所以各階段實際花費未知。
- `gh` CLI 只能用於搜尋；PR 操作請使用 GitHub MCP 工具。
