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
| #12 | Excel 欄位對應器（`core/field_mapper.py`、`pages/1_Excel_欄位對應.py`） | 進行中（分支 `claude/pr12-field-mapper`） |
| #13 | 示範與銷售素材 | 未開始 |
| #14 | 品質與效能（1k～50k 列） | 未開始 |
| #15 | 客戶交付工具包 | 未開始 |

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

## 下一步建議（依價值排序）

1. 在客戶或自己的 Windows／macOS 電腦上，用 repo 原始 Dockerfile 執行 `docker compose up --build`，並完成一次三檔上傳（目前只在雲端開發環境驗證過，且當時以 build secret 傳入 proxy CA）。
2. 依 `docs/GO_TO_MARKET.md` 進行真實訪談（目標 10 位）。這一步需要真人執行，AI 不能代勞或虛構結果。
3. 取得第一份經授權、已去識別化的真實資料，依 `docs/CUSTOMER_ONBOARDING.md` 做欄位對應，記錄實際花費時間。
4. 依真實資料調整報價狀態對照、欄位別名；不要先開發多階 BOM 或匯率功能。

## 環境備忘

- 雲端開發環境的 Docker build：先啟動 `dockerd`，再執行
  `docker buildx build --network host --secret id=corp_ca,src=/root/.ccr/ca-bundle.crt -t spi --load .`
- 額度：使用者回報剩餘 US$86（2026-11-04 開始時）。session 內無法讀取實際用量，所以各階段實際花費未知。
- `gh` CLI 只能用於搜尋；PR 操作請使用 GitHub MCP 工具。
