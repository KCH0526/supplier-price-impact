# 公開網站操作說明

## 檔案位置

| 位置 | 內容 |
|---|---|
| `web/` | **唯一要部署的資料夾**，只有靜態的 HTML、CSS、JS、`sitemap.xml`、`robots.txt` |
| `web_src/build_site.py` | 網站產生腳本（共用版面、canonical、sitemap） |
| `web_src/content/` | 各頁內容片段與 6 篇教學 |
| `web_src/demo_content.py` | 用合成資料預先算出 Demo 結果的腳本 |

## 修改內容後重新產生

```bash
python web_src/build_site.py
```

執行後，`web/` 會被重新產生。測試會檢查 `web/` 是否與產生結果一致。

## 本機預覽

```bash
python -m http.server 8000 --bind 127.0.0.1 --directory web
```

然後開啟 `http://127.0.0.1:8000`。

## 更換正式網域（部署前必做）

1. 把 `web_src/build_site.py` 的 `BASE_URL` 從 `https://example.com/` 改成正式網址，結尾要有 `/`。
2. 把 `tests/test_web_site.py` 的 `BASE` 改成同一個網址。
3. 執行 `python web_src/build_site.py` 與 `python -m pytest -q`。
4. 在 `contact.html` 的內容片段中填入正式的聯絡方式。

## 部署選項（需要你決定並授權；本專案不會自行部署）

只要上傳 `web/` 資料夾即可，不需要任何伺服器程式。常見選項如下：

- **GitHub Pages**：適合程式碼本來就放在 GitHub 的情況。
- **Cloudflare Pages**、**Netlify**：同樣是靜態網站託管服務。
- **公司既有的網頁主機**：可以直接放靜態檔案。

各平台的免費額度、限制與費用，請以官方最新公告為準。

**絕對不要部署 `app.py`、`pages/` 或 Docker 映像到公開網路。**
