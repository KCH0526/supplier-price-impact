"""Pre-generate the public demo pages from the repository's synthetic data.

Runs the existing core/ modules once at build time and renders static HTML.
The published site therefore contains no server code and no upload path.
Every value is HTML-escaped.
"""

from __future__ import annotations

import datetime as dt
import html
import json
import sys
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

NOTICE = ('<p class="notice"><strong>這是合成示範資料</strong>：所有公司、客戶、料號與金額都是人工建構的，'
          '不是任何企業的真實資料。本頁是預先產生的靜態頁面，不接受任何檔案或資料輸入。</p>')
AS_OF = dt.date(2026, 12, 1)


def cell(value) -> str:
    if value is None:
        return "—"
    if isinstance(value, Decimal):
        return f"{value:,.2f}"
    if isinstance(value, (dt.datetime, dt.date)):
        return value.isoformat()[:10]
    return html.escape(str(value))


def pct(value) -> str:
    return "—" if value is None else f"{value * 100:.2f}%"


def table(headers, rows, numeric=()) -> str:
    num = ' class="num"'
    head = "".join(f"<th{num if h in numeric else ''}>{html.escape(h)}</th>" for h in headers)
    body = "\n".join("<tr>" + "".join(
        f"<td{num if h in numeric else ''}>{v}</td>" for h, v in zip(headers, r)) + "</tr>" for r in rows)
    return f'<div class="table-scroll"><table><thead><tr>{head}</tr></thead><tbody>\n{body}\n</tbody></table></div>'


def nav(root: str) -> str:
    items = [("index.html", "總覽"), ("cost.html", "漲價前後"), ("quote-risk.html", "毛利風險"), ("history.html", "歷史報價"),
             ("tiers.html", "數量階梯"), ("versions.html", "版本差異"), ("draft.html", "客戶草稿")]
    return '<p>示範頁：' + "　".join(f'<a href="{root}demo/{p}">{t}</a>' for p, t in items) + "</p>"


def _costs():
    from core.calculator import calculate_cost_impact
    from core.matcher import match_prices
    from core.reader import read_bom, read_price_increase, read_sheet
    bom = ROOT / "samples" / "sample_bom.xlsx"
    matched = match_prices(read_bom(bom).data, read_price_increase(ROOT / "samples" / "sample_price_increase.xlsx").data, AS_OF)
    return matched, calculate_cost_impact(matched, read_sheet(bom, "ProductCost", ["成品編號"]).data)


def _history():
    from core.historical_quotes import HistoricalSource, import_historical_quotes
    hist = ROOT / "samples" / "historical"
    sources = []
    for name, file in (("sales_dept", "historical_quotes_sales_dept.xlsx"),
                       ("legacy_system", "historical_quotes_legacy_system.xlsx")):
        m = json.loads((hist / f"mapping_{name}.json").read_text(encoding="utf-8"))["targets"]["HistoricalQuotes"]
        sources.append(HistoricalSource(file, (hist / file).read_bytes(), m["source_sheet"], m["columns"]))
    return import_historical_quotes(sources).records


def index_page(root: str) -> str:
    return f"""<h1>合成資料示範</h1>
{NOTICE}
<p class="lead">不用上傳任何檔案，就能看到完整系統在一家虛構工廠的資料上算出的結果。試算基準日 2026-12-01（歷史報價與報價工作台為 2026-12-15）。</p>
<div class="cards">
  <div class="card"><h3><a href="{root}demo/cost.html">供應商漲價前後</a></h3><p>6 個成品的成本變化與月成本影響。</p></div>
  <div class="card"><h3><a href="{root}demo/quote-risk.html">毛利風險</a></h3><p>8 張有效客戶報價中，哪些跌破 15% 毛利底線。</p></div>
  <div class="card"><h3><a href="{root}demo/history.html">歷史報價</a></h3><p>兩種格式的舊報價合併後，哪些可以比較、哪些不行。</p></div>
  <div class="card"><h3><a href="{root}demo/tiers.html">數量階梯</a></h3><p>10、100、500 件的安全底價（試算）。</p></div>
  <div class="card"><h3><a href="{root}demo/versions.html">報價版本差異</a></h3><p>同一張報價單兩個版本差在哪裡。</p></div>
  <div class="card"><h3><a href="{root}demo/draft.html">客戶報價草稿</a></h3><p>只包含客戶可以看的欄位。</p></div>
</div>
<p>想用自己的資料試算，請使用<a href="{root}enterprise.html">企業私有版</a>，資料只在貴公司內部處理。</p>"""


def cost_page(root: str) -> str:
    _, costs = _costs()
    rows = [[cell(r["成品編號"]), cell(r["成品名稱"]), cell(r["原成本"]), cell(r["新成本"]), cell(r["成本增加"]),
             pct(r["成本增加百分比"]), cell(r["預估月產量"]), cell(r["預估月成本增加"])]
            for r in costs.cost_impact.to_dict("records")]
    total = costs.summary["預估每月總成本增加"]
    return f"""<h1>供應商漲價前後</h1>
{NOTICE}
{nav(root)}
<p>供應商調漲 11 個料號後，逐行計算每個成品的完整成本（材料＋人工＋製費＋其他）。</p>
{table(["成品", "名稱", "原成本", "新成本", "每件增加", "增加百分比", "月產量", "月成本增加"], rows,
       numeric=("原成本", "新成本", "每件增加", "增加百分比", "月產量", "月成本增加"))}
<p>預估每月總成本增加：<strong>{cell(total)}</strong> 元。調價清單中的 M-999 不在 BOM 中，系統把它列為例外，不影響其他成品。</p>"""


def risk_page(root: str) -> str:
    from core.quote_reader import read_open_quotes
    from core.quote_risk import assess_quote_risk
    _, costs = _costs()
    risk = assess_quote_risk(read_open_quotes(ROOT / "samples" / "sample_open_quotes.xlsx").data, costs, AS_OF)
    rows = [[cell(r["風險排序"]), cell(r["覆核狀態"]), cell(f"{r['報價單號']} / {r['行號']}"), cell(r["成品編號"]),
             cell(r["未稅報價單價"]), pct(r["原毛利率"]), pct(r["新毛利率"]), cell(r["維持底線所需最低單價"]), cell(r["問題原因"])]
            for r in risk.risk.to_dict("records")]
    return f"""<h1>客戶報價毛利風險</h1>
{NOTICE}
{nav(root)}
<p>毛利底線 15%。依風險排序：越前面越需要優先人工覆核。「維持底線所需最低單價」已無條件進位。</p>
{table(["排序", "狀態", "報價單號／行號", "成品", "報價單價", "原毛利率", "新毛利率", "維持底線最低單價", "原因"], rows,
       numeric=("排序", "報價單價", "原毛利率", "新毛利率", "維持底線最低單價"))}
<p>依報價數量推估的情境成本增加不是實際損失；系統不會修改或寄送任何報價。</p>"""


def history_page(root: str) -> str:
    from core.quote_advisor import advise_quote
    from core.quote_search import search_similar_quotes
    records = _history()
    _, costs = _costs()
    as_of = dt.date(2026, 12, 15)
    search = search_similar_quotes(records, "P-1001", 60, as_of, "pcs", drawing_version="B")
    advice = advise_quote(search, records, costs, Decimal("0.15"), price_increase_date=AS_OF)
    rows = [[cell(r["判定"]), cell(r["原因"]), cell(r["報價單號"]), cell(r["報價日期"]), cell(r["客戶代碼"]),
             cell(r["報價數量"]), cell(r["計價單位"]), cell(r["報價單價"])] for r in advice.candidates.to_dict("records")]
    warns = "".join(f"<li><strong>{cell(w['類型'])}</strong>：{cell(w['說明'])}</li>" for w in advice.warnings)
    return f"""<h1>歷史報價參考</h1>
{NOTICE}
{nav(root)}
<p>查詢條件：成品 P-1001、60 件、pcs、圖面版次 B、試算日 2026-12-15、目標毛利率 15%。兩種格式的歷史報價合併後，同一筆重複匯出的報價只保留一次。</p>
<p>覆核狀態：<strong>{cell(advice.status)}</strong>。安全底價 <strong>{cell(advice.floor['安全底價'])}</strong>（{cell(advice.floor['計算式'])}）。</p>
<h2>每一筆歷史報價的判定</h2>
{table(["判定", "原因", "報價單號", "日期", "客戶代碼", "數量", "單位", "單價"], rows, numeric=("數量", "單價"))}
<h2>警示</h2><ul>{warns}</ul>
<p>歷史報價不是成交價；歷史證據含其他客戶的價格，在企業版中只出現在內部報告，不會出現在客戶草稿。</p>"""


def tiers_page(root: str) -> str:
    from core.batch_cost import MODE_DETAILED, cost_model_for, read_batch_costs
    from core.quantity_tiers import compute_quantity_tiers
    model = cost_model_for("P-DEMO", MODE_DETAILED, AS_OF,
                           batch=read_batch_costs(ROOT / "samples" / "batch_cost" / "batch_cost_sample.xlsx"), version="A")
    res = compute_quantity_tiers(model, [10, 100, 500], Decimal("0.20"))
    rows = [[cell(r["數量"]), cell(r["每件分攤固定費"]), cell(r["每件情境成本"]), cell(r["安全底價（試算）"])]
            for r in res.rows.to_dict("records")]
    return f"""<h1>數量階梯</h1>
{NOTICE}
{nav(root)}
<p>明細批次成本：單件變動成本 {cell(model.unit_variable)} 元（材料＋人工＋製費＋委外），每批固定費 {cell(model.batch_fixed)} 元（開機＋換線治具），目標毛利率 20%。</p>
{table(["數量", "每件分攤固定費", "每件成本", "安全底價（試算）"], rows, numeric=("數量", "每件分攤固定費", "每件成本", "安全底價（試算）"))}
<p>安全底價＝每件成本 ÷（1 − 20%），無條件進位到小數兩位。這只是下限，不是系統核准的售價。</p>
<p>若改用「既有完整單件成本」模式，系統會標示批次固定費「未計入」，避免和既有製費重複計算。本示範未模擬數量對原料議價、良率、工時的影響。</p>"""


def versions_page(root: str) -> str:
    from core.quote_versions import compare_quote_versions
    res = compare_quote_versions(_history(), "Q-2603-007", "1", "1", "2")
    def show(v):
        return cell(v)
    rows = [[cell(r["欄位"]), show(r["舊值"]), show(r["新值"]), cell(r["差額"]),
             "—" if r["差異百分比"] is None else f"{r['差異百分比']}%", cell(r["說明"])] for r in res.rows.to_dict("records")]
    return f"""<h1>報價版本差異</h1>
{NOTICE}
{nav(root)}
<p>報價單 Q-2603-007 第 1 行的第 1 版與第 2 版。{cell(res.message)}。</p>
{table(["欄位", "舊值", "新值", "差額", "差異百分比", "說明"], rows, numeric=("差額", "差異百分比"))}
<p>單價差額只有在幣別、計價單位、稅別、數量都相同時才計算；同一天的兩個版本需由使用者指定先後，系統不依版本號猜測。</p>"""


def draft_page(root: str) -> str:
    from core.customer_draft import ALLOWED_HEADER, ALLOWED_LINE, build_customer_draft
    header = {"客戶代碼": "C-001", "客戶名稱": "北辰自動化（虛構）", "報價單號": "SQ-DEMO-1", "報價版本": "1",
              "報價日期": dt.date(2026, 12, 15), "報價有效期限": dt.date(2027, 1, 14), "交易條件": "月結 30 天"}
    lines = [{"成品編號": "P-DEMO", "成品名稱": "示範零件", "數量": q, "計價單位": "pcs", "幣別": "TWD", "報價單價": p,
              "交期": "15 天"} for q, p in ((10, "420"), (100, "250"), (500, "235"))]
    draft = build_customer_draft(header, lines, prices_confirmed=True)
    head = "".join(f"<tr><th>{cell(k)}</th><td>{cell(draft.header[k])}</td></tr>" for k in ALLOWED_HEADER)
    cols = [*ALLOWED_LINE, "合計金額"]
    rows = [[cell(l.get(c)) for c in cols] for l in draft.lines]
    return f"""<h1>客戶報價草稿</h1>
{NOTICE}
{nav(root)}
<p>草稿以<strong>允許欄位清單</strong>組成：只有客戶可以看的欄位。示範中的單價是「由人填寫」的示範數字，系統不會自動帶入任何價格。</p>
<!-- draft-start -->
<h2>{cell(draft.label)}</h2>
<div class="table-scroll"><table><tbody>{head}</tbody></table></div>
{table(cols, rows, numeric=("數量", "報價單價", "合計金額"))}
<p>合計：{cell(draft.total)} 元</p>
<!-- draft-end -->
<p>系統不核准、不簽名、不寄送；正式報價須依公司流程由權責主管核准。</p>"""


PAGES = {
    "demo/index.html": ("合成資料示範｜不上傳檔案也能看懂結果",
                        "以完全合成的示範資料，看供應商漲價、毛利風險、歷史報價、數量階梯、版本比較與客戶草稿的結果。", index_page),
    "demo/cost.html": ("示範：供應商漲價前後的成品成本（合成資料）",
                       "以合成資料示範供應商調漲 11 個料號後，6 個成品的完整成本變化與月成本影響。", cost_page),
    "demo/quote-risk.html": ("示範：客戶報價毛利風險（合成資料）",
                             "以合成資料示範 8 張有效客戶報價在漲價後的毛利率、跌破 15% 底線的報價與最低單價。", risk_page),
    "demo/history.html": ("示範：歷史報價參考與安全底價（合成資料）",
                          "以合成資料示範歷史報價逐筆選入或排除的原因、安全底價與警示。", history_page),
    "demo/tiers.html": ("示範：數量階梯安全底價（合成資料）",
                        "以合成資料示範 10、100、500 件在批次固定費分攤後的每件成本與安全底價。", tiers_page),
    "demo/versions.html": ("示範：報價版本差異比較（合成資料）",
                           "以合成資料示範同一張報價單兩個版本的單價、金額與成交狀態差異。", versions_page),
    "demo/draft.html": ("示範：只含客戶可見欄位的報價草稿（合成資料）",
                        "以合成資料示範依允許欄位清單產生的客戶報價草稿，不含成本、底價或其他客戶資料。", draft_page),
}
