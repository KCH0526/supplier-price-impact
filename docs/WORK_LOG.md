# 工作紀錄（給下一個開發 session）

每完成一個 PR 就更新本檔。新的 session 請先讀本檔，再從最新 `main` 建立分支繼續。

## 目前進度

| PR | 內容 | 狀態 |
|---|---|---|
| #1～#5 | 目錄整理、讀取驗證、配對、成本計算、Streamlit、Docker | 已合併 |
| #6 | Python 3.11／Docker／安全驗收、CI | 已合併（main `70ee1bb`） |
| #7 | OpenQuotes 讀取與驗證、產品決策紀錄 | 進行中 |
| #8 | 毛利風險覆核引擎 `core/quote_risk.py` | 未開始 |
| #9 | Streamlit 三檔上傳、Quote Risk 報告、README | 未開始 |
| #10 | 對抗測試、交付文件（ONBOARDING、GO_TO_MARKET） | 未開始 |

## 常用指令

```bash
python3.11 -m venv .venv && . .venv/bin/activate
python -m pip install -r requirements.txt
python -m pytest -q -rs     # 必須 0 failed、0 skipped
```

## 不可修改

- `docs/IMPLEMENTATION_SPEC.md`
- `samples/sample_bom.xlsx`、`samples/sample_price_increase.xlsx`
- `tests/fixtures/` 內既有的三份驗收檔

新增的合成檔（`samples/sample_open_quotes.xlsx`、
`tests/fixtures/test_open_quotes_edge_cases.xlsx`）同樣視為驗收資料，不得為了讓測試通過而修改。

## 環境備忘

- 雲端開發環境的 Docker build 需要以 `--network host` 執行，並另外信任 proxy CA；
  詳見 `docs/DEPLOYMENT_CHECKLIST.md`。repo 內的 Dockerfile 不包含這一步。
- `gh` CLI 只能用於搜尋；PR 操作請使用 GitHub MCP 工具。
