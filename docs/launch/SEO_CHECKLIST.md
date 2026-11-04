# SEO 驗收清單

## 已由自動化測試確認（`tests/test_web_site.py`，結果：通過）

| 項目 | 結果 |
|---|---|
| 每頁都有不重複的 `<title>` 與 meta description（10～160 字） | 通過 |
| `lang="zh-Hant-TW"`、viewport | 通過 |
| canonical 網址與 sitemap 一致 | 通過（目前使用暫定的 `BASE_URL` = `https://example.com/`） |
| `robots.txt` 指向 sitemap | 通過 |
| 內部連結全部有效 | 通過 |
| 跳到主要內容、`<main>`、表單元件都有 label | 通過 |
| 6 篇教學都有實際步驟與例子 | 通過 |
| 手機與桌機沒有水平捲動（瀏覽器實測） | 通過 |

## 尚未完成（需要上線後才能做）
- [ ] 把 `BASE_URL` 改成正式網域並重新產生（`PUBLIC_SITE_GUIDE.md`）。
- [ ] 在 Google Search Console 驗證網站並提交 sitemap（需要使用者的帳號）。
- [ ] 檢查正式網址的 HTTPS 與重新導向。
- [ ] 實測行動裝置的載入速度。
- [ ] 視需要加入結構化資料（例如 FAQ）。
- [ ] 依真實讀者的提問，持續新增或修訂教學，不大量產生內容空泛的頁面。
