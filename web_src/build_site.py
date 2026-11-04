"""Build the static public website from web/content/ fragments.

    python web_src/build_site.py

Reads web_src/content/ fragments and writes the HTML pages, sitemap.xml and
robots.txt into web/ (the only folder to deploy). No server code,
no external resources, no tracking. Replace BASE_URL before deployment.
"""

from __future__ import annotations

from pathlib import Path

import sys

SRC = Path(__file__).resolve().parent
sys.path.insert(0, str(SRC))
import demo_content  # noqa: E402
WEB = SRC.parent / "web"
CONTENT = SRC / "content"
BASE_URL = "https://example.com/"   # 部署前改成正式網域
SITE = "製造業報價毛利覆核工具"

# path: (title, description, fragment)
PAGES = {
    "index.html": ("供應商漲價與報價毛利覆核｜台灣少量多樣製造業",
                   "供應商漲價後，找出哪些成品成本變了、哪些客戶報價會跌破毛利底線。提供免費試算工具、教學與合成資料示範。",
                   "index.html"),
    "features.html": ("功能介紹｜成本影響、毛利風險、歷史報價、數量階梯",
                      "四大功能：供應商漲價成本影響、客戶報價毛利風險、歷史報價參考、批次成本與數量階梯。每個數字都可追溯。",
                      "features.html"),
    "industries.html": ("適用產業與解決的問題｜金屬加工、零組件、設備組裝",
                        "適合少量多樣、報價依賴 Excel 的台灣製造業：金屬加工、機械零組件、設備組裝、中小型代工。",
                        "industries.html"),
    "tools/index.html": ("免費報價試算工具｜成本增幅、毛利率、批次分攤、數量階梯",
                         "四個免費小工具，全部在您的瀏覽器內計算，不會傳送任何數字：成本增加百分比、毛利率與加價率、批次固定費分攤、數量階梯最低售價。",
                         "tools.html"),
    "enterprise.html": ("企業私有版與導入服務｜資料留在公司內部",
                        "完整系統在貴公司電腦或內網執行，真實資料不上傳到公開網站。提供欄位對應、報價覆核與維護服務（價格待驗證）。",
                        "enterprise.html"),
    "install.html": ("安裝與使用方式｜Python 或 Docker 在本機執行",
                     "企業私有版的安裝步驟：Python 3.11 或 Docker，只在本機或公司內網執行，並附上第一次使用的操作順序。",
                     "install.html"),
    "faq.html": ("常見問題｜資料安全、ERP、毛利率、報價草稿",
                 "關於資料是否上傳、能否讀取 ERP 檔、毛利率口徑、客戶報價草稿與費用的常見問題。",
                 "faq.html"),
    "privacy.html": ("隱私與安全說明｜不蒐集計算器輸入、不使用追蹤",
                     "本網站的計算器只在瀏覽器內計算，不蒐集輸入資料，不使用 cookie、分析工具或廣告追蹤。",
                     "privacy.html"),
    "contact.html": ("聯絡與試用申請說明｜請勿寄送機密檔案",
                     "如何洽詢企業私有版試用：先看合成資料示範、準備問題清單；第一次聯絡請勿附上任何真實 BOM 或報價檔。",
                     "contact.html"),
    "articles/index.html": ("報價實務教學｜成本、毛利、批次費、MOQ、歷史報價",
                            "六篇有實際步驟與例子的報價實務教學，適合業務、成本會計與報價主管。",
                            "articles/index.html"),
    "articles/bom-price-increase.html": ("BOM 漲價如何影響成品成本｜共用料件與逐行計算",
                                         "供應商調漲一個料號，會影響哪些成品？以逐行 BOM 計算說明共用料件、未調價料件與成本增加百分比。",
                                         "articles/bom-price-increase.html"),
    "articles/margin-vs-markup.html": ("毛利率與加價率的差異｜為什麼 20% 不等於 20%",
                                       "毛利率以售價為分母，加價率以成本為分母。說明兩者換算、常見誤用，以及要達到毛利底線的最低售價。",
                                       "articles/margin-vs-markup.html"),
    "articles/batch-setup-cost.html": ("少量多樣的開機費與換線費怎麼分攤｜批次固定費",
                                       "開機、換線、治具等批次固定費要依數量攤提。以 10、100、500 件的例子說明每件成本與最低售價。",
                                       "articles/batch-setup-cost.html"),
    "articles/moq-pricing.html": ("MOQ 最低訂購量如何影響報價｜小量訂單的報價方式",
                                  "最低訂購量和固定費攤提有直接關係。說明 MOQ 的計算依據、低於 MOQ 時的處理方式與報價注意事項。",
                                  "articles/moq-pricing.html"),
    "articles/historical-quotes.html": ("歷史報價為什麼不能直接沿用｜版次、數量、稅別與成交",
                                        "舊報價不一定能比：圖面版次、數量級距、含稅與否、幣別、是否成交都會影響。說明檢查清單。",
                                        "articles/historical-quotes.html"),
    "articles/erp-excel-cleanup.html": ("ERP 匯出 Excel 如何整理｜欄位、前導零、單位與日期",
                                        "從 ERP 匯出 BOM、調價與報價資料時，常見的前導零遺失、單位不一致、日期格式問題與整理步驟。",
                                        "articles/erp-excel-cleanup.html"),
}
PAGES.update(demo_content.PAGES)

NAV = [("index.html", "首頁"), ("features.html", "功能"), ("industries.html", "適用產業"), ("tools/index.html", "免費工具"),
       ("demo/index.html", "合成資料示範"), ("articles/index.html", "教學"), ("enterprise.html", "企業版"),
       ("faq.html", "常見問題")]


def _rel(target: str, current: str) -> str:
    depth = current.count("/")
    return "../" * depth + target


def page(path: str) -> str:
    title, description, fragment = PAGES[path]
    root = "../" * path.count("/")
    body = fragment(root) if callable(fragment) else (CONTENT / fragment).read_text(encoding="utf-8").replace("{{ROOT}}", root)
    canonical = BASE_URL + ("" if path == "index.html" else path)
    current = ' aria-current="page"'
    nav = "\n".join(
        f'        <li><a href="{_rel(t, path)}"{current if t == path else ""}>{label}</a></li>'
        for t, label in NAV)
    return f"""<!doctype html>
<html lang="zh-Hant-TW">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title}</title>
  <meta name="description" content="{description}">
  <link rel="canonical" href="{canonical}">
  <link rel="stylesheet" href="{_rel('assets/style.css', path)}">
</head>
<body>
  <a class="skip-link" href="#main">跳到主要內容</a>
  <header class="site-header">
    <div class="wrap">
      <a class="brand" href="{_rel('index.html', path)}">{SITE}</a>
      <nav aria-label="主要選單">
        <ul>
{nav}
        </ul>
      </nav>
    </div>
  </header>
  <main id="main" class="wrap">
{body}
  </main>
  <footer class="site-footer">
    <div class="wrap">
      <p>本網站的示範資料全部是合成資料；試算結果僅供參考，不是正式報價，也不代表任何企業的真實成本。</p>
      <p><a href="{_rel('privacy.html', path)}">隱私與安全說明</a>　<a href="{_rel('contact.html', path)}">聯絡與試用申請</a>　<a href="{_rel('install.html', path)}">安裝與使用方式</a></p>
    </div>
  </footer>
</body>
</html>
"""


def build() -> dict[str, str]:
    out = {path: page(path) for path in PAGES}
    urls = "\n".join(f"  <url><loc>{BASE_URL}{'' if p == 'index.html' else p}</loc></url>" for p in PAGES)
    out["sitemap.xml"] = ('<?xml version="1.0" encoding="UTF-8"?>\n'
                          '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n' + urls + "\n</urlset>\n")
    out["robots.txt"] = f"User-agent: *\nAllow: /\n\nSitemap: {BASE_URL}sitemap.xml\n"
    return out


if __name__ == "__main__":
    for path, text in build().items():
        target = WEB / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    print(f"wrote {len(PAGES)} pages, sitemap.xml and robots.txt")
