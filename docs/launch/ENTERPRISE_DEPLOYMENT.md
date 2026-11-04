# 企業私有版部署說明

企業私有版就是 repo 中完整的 Streamlit 系統。它**沒有登入與企業隔離**，只能在客戶的電腦或公司內網執行。

## 部署前確認
- 由客戶 IT 決定執行環境：個人電腦、內網伺服器或虛擬機。
- 只綁定本機或內網位址；不設定對外的連接埠轉發。
- 若需要多人使用，放在公司既有的 HTTPS 反向代理與存取控制之後（本系統本身沒有登入功能）。

## 安裝方式
詳見 [`../DEPLOYMENT_CHECKLIST.md`](../DEPLOYMENT_CHECKLIST.md)：
- Python 3.11：`streamlit run app.py --server.address=127.0.0.1`
- Docker：`docker compose up --build`，只綁定 `127.0.0.1:8501`，以非 root 帳號執行
- 公司網路有 SSL 檢查 proxy 時：`docker build --secret id=corp_ca,src=公司CA.crt .`

## 驗收
1. 先用 `samples/` 的合成資料跑一次，結果與 README 一致。
2. 再依 `../delivery/` 的流程導入真實資料。

Windows 與 macOS 的 Docker Desktop 尚未經過實機驗證，第一次導入時要一併確認。
