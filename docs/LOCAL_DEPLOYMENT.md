# 本機部署與驗收說明（企業內部版 Release Candidate）

適用版本：main `d3801c8` 之後（PR #37 起）　｜　適用範圍：**一家企業、一台電腦、一位使用者**

本系統只在本機執行，沒有登入、角色與權限，**不支援多使用者**；不連線到外部 API 或服務。
「案件工作台」的操作人欄位是「人工填寫（未經身分驗證）」，不是電子簽核。

> 實測狀況（三種層級，請勿混為一談）：
> 1. **開發環境 Linux 與 Docker**：Python 3.11.18 與 `python:3.11-slim` 已實際安裝，並完成完整測試與瀏覽器端對端驗收。
> 2. **GitHub-hosted runner**（PR #38 起，每個 PR 自動執行）：Windows Server 2025 x64 與 macOS 26 arm64，Python 3.11.9、Node.js 22，以 `requirements-lock.txt` 安裝。567 passed、0 failed、0 skipped（見第 13 節）。這證明鎖定的套件可以安裝，且程式與測試可以跨作業系統執行。
> 3. **客戶的實體電腦、Windows 10/11 桌機、Intel Mac、Docker Desktop**：**尚未在實機驗證**。runner 是乾淨的雲端虛擬機，沒有公司防毒、權限政策、中文使用者名稱、OneDrive 等真實環境因素。第一次安裝時，請照第 7 節做一次驗收並記錄結果。

## 1. 安裝前準備
- Python **3.11**（3.11.x 皆可；其他版本未驗收）。
- 約 1 GB 可用磁碟空間（套件約 400 MB，另加資料與備份）。
- 一個**本機磁碟**上的資料夾，用來放資料庫與備份（見第 4 節）。
- 安裝一律使用 `requirements-lock.txt`：它固定了所有直接與傳遞依賴的版本，與通過驗收的環境完全相同。
  `requirements.txt` 只列出直接依賴，不建議單獨使用。

## 2. Windows 安裝
在 PowerShell 中執行（以 `C:\報價工具` 為例）：

```powershell
py -3.11 --version
cd C:\報價工具\supplier-price-impact
py -3.11 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements-lock.txt
python -m pytest -q -rs
streamlit run app.py
```

- 若出現「因為這個系統上已停用指令碼執行」：執行 `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` 後重開 PowerShell，或改用 `.venv\Scripts\activate.bat`（命令提示字元）。
- `pytest` 必須是 0 failed、0 skipped 才算安裝成功。
- 瀏覽器開啟 `http://127.0.0.1:8501`。Windows 防火牆若詢問是否允許連線，請選「取消」或只允許「私人網路」；本系統不需要讓其他電腦連入。

## 3. macOS 安裝
在「終端機」中執行（Python 3.11 可由 python.org 安裝程式或 Homebrew `brew install python@3.11` 取得）：

```bash
python3.11 --version
cd ~/報價工具/supplier-price-impact
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-lock.txt
python -m pytest -q -rs
streamlit run app.py
```

瀏覽器開啟 `http://127.0.0.1:8501`。macOS 若詢問是否允許「Python」接受連入連線，請選「拒絕」。

## 4. Docker 啟動
Docker 映像同樣以 `requirements-lock.txt` 安裝，並以非 root 使用者（uid 10001）執行。

只使用前三份報表功能、不保存案件時：

```bash
docker compose up --build
```

要使用「案件工作台」保存案件時，必須掛載一個資料夾到 `/data`，資料庫路徑填 `/data/cases.db`：

```bash
docker build -t supplier-price-impact .
docker run -d --name spi -p 127.0.0.1:8501:8501 -v /path/to/case_data:/data supplier-price-impact
```

- Linux 主機需讓 uid 10001 可寫入該資料夾（例如 `sudo chown 10001:10001 /path/to/case_data`）。Docker Desktop（Windows／macOS）通常不需要。
- 連接埠**必須**寫成 `127.0.0.1:8501:8501`，不可寫成 `8501:8501`。
- 沒有掛載資料夾時，資料只在容器內，刪除容器就會消失。

## 5. 本機資料庫位置
資料保存**預設關閉**。在「案件工作台」勾選「啟用本機保存」並輸入完整路徑後，才會建立資料庫。

| 系統 | 建議路徑 |
|---|---|
| Windows | `D:\報價資料\cases.db`（或 `C:\Users\<帳號>\報價資料\cases.db`） |
| macOS | `/Users/<帳號>/報價資料/cases.db` |
| Docker | `/data/cases.db`（對應主機上掛載的資料夾） |

不要放在：
- 網路共享磁碟（`\\server\...`、`//server/...`，系統會拒絕）、NAS 掛載磁碟。
- OneDrive、Dropbox、Google Drive、iCloud 等**同步資料夾**（包含 macOS 開啟「桌面與文件」同步時的「文件」資料夾）。同步程式可能在寫入中途複製檔案，造成資料庫損毀。
- 專案資料夾（`supplier-price-impact` 內）。`.gitignore` 雖已排除 `*.db`、`case_backups/`、`case_data/`，仍應放在專案外，避免誤加入 Git。

## 6. 磁碟權限與加密建議
- 權限：資料夾只給使用這台電腦的報價人員帳號讀寫。
  - Windows：資料夾「內容 → 安全性」移除 `Users`／`Everyone`，只保留該帳號與系統管理員。
  - macOS／Linux：`chmod 700 ~/報價資料`。
- **SQLite 檔案沒有加密**。請啟用整顆磁碟加密：Windows 使用 BitLocker（或「裝置加密」），macOS 使用 FileVault。
- 備份檔與資料庫同樣含成本與毛利，外接硬碟或隨身碟也必須加密（BitLocker To Go、APFS 加密）。
- 內部稽核報告含成本與實際成本；只有「客戶報價草稿」可以給客戶。

## 7. 安裝後驗收（每台電腦第一次安裝時做一次）
1. `python -m pytest -q -rs`：0 failed、0 skipped。
2. 開啟「案件工作台」，確認預設顯示「資料保存未啟用」。
3. 啟用保存，路徑填一個**測試用**資料庫（例如 `D:\報價資料\test_cases.db`），上傳 `samples/rfq/rfq_sample.xlsx`，填原因並保存，應顯示「已保存」。
4. 選擇 `C-001|RFQ-2612-001|v1`：狀態改為待人工覆核；新增報價版本（單價 300、數量 100、預估單位成本 200）；回填成交、數量 100、實際總成本 22500。差異表應顯示預估 33.33%、實際 25.00%、下降 8.33 個百分點。
5. 建立備份 → 未勾選確認時還原應被拒絕 → 勾選後還原成功。
6. 驗收完成後刪除測試資料庫與測試備份，再建立正式資料庫。

## 8. 備份
- 在「案件工作台 → ④ 備份與還原」輸入備份檔路徑並按「建立備份」。系統使用 SQLite 線上備份，不直接複製正在使用的檔案；已存在的檔名不會被覆蓋。
- 建議：每天下班前一次；每週複製一份到加密的外接硬碟。至少保留最近 4 週。
- 建議檔名包含日期，例如 `D:\報價備份\cases_20261104.db`。
- 不要用檔案總管直接複製 `cases.db`，除非程式已完全關閉且同資料夾內沒有 `cases.db-journal` 檔案。

## 9. 還原
1. 在「要還原的備份檔路徑」輸入備份檔，畫面會先顯示完整性與資料結構版本檢查結果。
2. 檢查結果為「完整」且版本相同，才勾選「我確認要用這個備份覆蓋目前的資料庫」，再按「還原」。
3. 還原前，系統會自動把目前的資料另存為 `cases.before_restore_<時間>.db`（與資料庫同一資料夾）。若還原錯了，可再用這個檔案還原回來。

## 10. 更新程式前的備份流程
1. 確認沒有人正在操作，在「案件工作台」建立備份，檔名註明「更新前」（例如 `cases_before_update_20261104.db`）。
2. 確認備份檢查結果為「完整」，並把該備份另外複製到加密的外接硬碟。
3. 關閉程式（終端機按 Ctrl+C；Docker 執行 `docker stop spi`）。
4. **保留舊的程式資料夾**（例如改名為 `supplier-price-impact_舊版`），把新版放到新的資料夾。
5. 在新版資料夾重新建立 `.venv` 並執行 `python -m pip install -r requirements-lock.txt` 與 `python -m pytest -q -rs`（Docker 則重新 `docker build`）。
6. 啟動新版，指向原本的資料庫路徑。若新版需要升級資料結構，開啟時會自動升級；升級失敗會回滾，資料維持原狀。
7. 新版有問題時：關閉新版，改用舊版資料夾啟動。若資料庫已被新版升級，舊版會拒絕開啟（「請更新程式」），此時用第 1 步的「更新前」備份還原到**新的路徑**再以舊版開啟。

套件版本的更新必須另開 PR：在乾淨的 Python 3.11 環境安裝新版本、執行完整測試與瀏覽器驗收，通過後才以 `pip freeze` 結果更新 `requirements-lock.txt`，並在 `docs/WORK_LOG.md` 記錄。不要只為了「固定版本」而升級套件。

## 11. 失敗與復原

| 狀況 | 畫面上看到的訊息 | 可能原因 | 復原方式 |
|---|---|---|---|
| 資料庫無法開啟 | 「無法開啟資料庫 …（檔案可能損毀、不是案件資料庫、路徑是資料夾，或沒有讀寫權限）」 | 檔案損毀、路徑填成資料夾或其他檔案、被同步程式或防毒軟體鎖定、權限不足 | 原檔不會被修改。先確認路徑正確、檔案沒有被其他程式開啟；仍無法開啟時，把最近的完整備份**還原到新的路徑**（例如 `cases_recovered.db`）後改用新路徑，並保留損毀檔供日後檢查 |
| 備份損毀 | 「備份檔檢查：不是可用的案件資料庫」或「完整性檢查失敗」；還原時「備份檔無法使用」 | 備份在傳輸中損壞、外接硬碟故障、檔案不是本系統的備份 | 系統拒絕還原，目前資料不受影響。改用前一份備份；定期以第 9 節第 1 步檢查備份是否「完整」 |
| 儲存空間不足 | 寫入時「寫入失敗，已復原（rollback）：database or disk is full」；備份時「無法建立備份（請確認資料夾權限與剩餘空間）」 | 磁碟已滿 | 該次寫入已整筆回滾，不會留下一半的資料；失敗的備份不會留下不完整的檔案。清出空間（刪除舊的 `before_restore` 檔與過期備份前，先確認已有其他完整備份）後重做 |
| 權限不足 | 「無法開啟資料庫 …」或「無法建立備份 …」 | 資料夾不可寫入；Docker 掛載資料夾未給 uid 10001 寫入權限 | 確認該帳號對資料夾有讀寫權限（第 6 節）；Docker 見第 4 節 `chown` |
| 安裝套件失敗 | `pip install` 出現 `CERTIFICATE_VERIFY_FAILED`、`No matching distribution found` 或連線逾時 | 公司 SSL 檢查 proxy、Python 不是 3.11、無法連到 PyPI | SSL：向 IT 取得公司 CA，`python -m pip install --cert <CA檔> -r requirements-lock.txt`（Docker 見 `docs/DEPLOYMENT_CHECKLIST.md` 的 build secret）。版本：確認 `python --version` 為 3.11.x。不要改用 `requirements.txt` 的其他版本或移除版本固定 |
| 系統版本不相容 | 「資料庫版本 N 比程式支援的 M 新，請更新程式後再開啟」；或「備份檔版本 … 與程式版本 … 不同」 | 用舊版程式開啟新版建立／升級過的資料庫或備份 | 改用對應的新版程式；或依第 10 節第 7 步，以舊版產生的「更新前」備份還原到新路徑 |
| Python 版本不相容 | 安裝或執行時出現語法錯誤、套件找不到對應版本 | 不是 Python 3.11 | 安裝 Python 3.11，重新建立 `.venv` |

## 12. 安全設定（不可變更）
- 預設只允許本機使用：`.streamlit/config.toml` 設定 `server.address = "127.0.0.1"`；Docker 只發布在 `127.0.0.1:8501`。不要改成 `0.0.0.0` 或 `8501:8501`，不要設定路由器轉發或公開網址。
- 不要把資料庫、備份、真實的 RFQ／成本／報價 Excel 放進 Git 或上傳到 GitHub（`.gitignore` 已排除 `*.db`、`*.sqlite`、`*.sqlite3`、`*.db-journal`、`case_backups/`、`case_data/`）。測試與示範只使用 `samples/` 中的合成資料。
- 本系統不呼叫外部 API、不使用外部 AI、不寄送任何資料。
- 不支援多使用者：不要讓多台電腦同時開啟同一個資料庫，也不要把資料庫放在共享磁碟。

## 13. 跨作業系統 CI 證據（GitHub-hosted runner）
`.github/workflows/ci.yml` 對每個 PR 執行：
- `test`（Ubuntu，main 的必要檢查）
- `test-cross-os`（windows-latest、macos-latest）

三者都使用 Python 3.11、Node.js 22 與 `requirements-lock.txt`。任何 failed、error 或 skipped 都會讓 CI 失敗（`tools/ci_report.py`）。每次執行都會把 `pytest-junit.xml`、`pip-install.log`、`pip-freeze.txt` 保存為 artifact，保留 30 天。

| 環境 | 實際版本（PR #38 的執行紀錄） | 依賴安裝 | 結果 |
|---|---|---|---|
| Ubuntu（ubuntu-latest） | Ubuntu x64、Python 3.11.17、Node.js 22 | lock 中 38 個套件（colorama 依標記略過） | 567 passed、0 failed、0 skipped |
| Windows（windows-latest） | Windows Server 2025（10.0.26100）x64、Python 3.11.9、Node.js 22.23.4 | lock 全部 39 個套件（含只在 Windows 安裝的 colorama 0.4.6） | 567 passed、0 failed、0 skipped |
| macOS（macos-latest） | macOS 26.6.2 arm64、Python 3.11.9、Node.js 22.23.4 | lock 中 38 個套件（colorama 依標記略過） | 567 passed、0 failed、0 skipped |

在 Windows runner 上第一次執行時發現並修正了 2 個問題，都不是商業計算的問題：
- `tests/test_web_calculators.py` 以系統預設編碼（Windows 為 cp1252）讀取 Node.js 的 UTF-8 輸出，中文錯誤訊息導致 18 項失敗。修正方式是明確指定 UTF-8。
- `benchmarks/run_benchmark.py` 匯入只存在於 Unix 的 `resource` 模組，在 Windows 無法執行。改為：Windows 使用標準函式庫 `ctypes` 讀取 PeakWorkingSetSize；macOS 的 `ru_maxrss` 單位是位元組，修正了先前把它當成 KB 的換算錯誤。

測試沒有任何只適用於特定作業系統的 skip。

仍未驗證：Windows 10/11 桌面版、Intel Mac、中文或含空白的使用者名稱路徑、公司防毒與群組原則、Docker Desktop（Windows／macOS），以及以瀏覽器實際操作 Windows／macOS 上的網頁（CI 只執行 Streamlit AppTest，不開啟真實瀏覽器）。
