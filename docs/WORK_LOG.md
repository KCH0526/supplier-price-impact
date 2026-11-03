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
| #10 | 對抗測試、最終 Docker 回歸、交付紀錄 | 本 PR |

技術 MVP 已完成，以合成資料驗收。商業驗證尚未開始（見 `docs/GO_TO_MARKET.md` 第 9 節）。

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

1. 在客戶或自己的 Windows／macOS 電腦上，用 repo 原始 Dockerfile 執行 `docker compose up --build`，並完成一次三檔上傳（目前只在雲端開發環境驗證過，且需另加 proxy CA）。
2. 依 `docs/GO_TO_MARKET.md` 進行真實訪談（目標 10 位）。這一步需要真人執行，AI 不能代勞或虛構結果。
3. 取得第一份經授權、已去識別化的真實資料，依 `docs/CUSTOMER_ONBOARDING.md` 做欄位對應，記錄實際花費時間。
4. 依真實資料調整報價狀態對照、欄位別名；不要先開發多階 BOM 或匯率功能。

## 環境備忘

- 雲端開發環境的 Docker build 需要以 `--network host` 執行，並另外信任 proxy CA；
  詳見 `docs/DEPLOYMENT_CHECKLIST.md`。repo 內的 Dockerfile 不包含這一步。
- `gh` CLI 只能用於搜尋；PR 操作請使用 GitHub MCP 工具。
