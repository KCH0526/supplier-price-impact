"""Explainable similar-quote search over imported historical quotes (PR #17).

Rules: docs/HISTORICAL_QUOTE_PRODUCT_SPEC.md section 5. Only quotes for the
exact same product are listed; every one is marked included or excluded
with the reason. Statistics are only produced when at least MIN_COMPARABLE
quotes are included; otherwise the result says the history is insufficient.
Historical quotes are not deal prices.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from decimal import Decimal

import pandas as pd

from core.validation import is_blank, parse_number

INCLUDED = "選入"
EXCLUDED = "排除"
GRADE_A = "A"
GRADE_B = "B"
REFERENCE_OK = "可參考"
INSUFFICIENT = "歷史資料不足"

MIN_COMPARABLE = 3
QTY_LOW, QTY_HIGH = Decimal("0.5"), Decimal("2")
MAX_AGE_DAYS = 730

SHOWN = ["判定", "等級", "原因", "同客戶", "舊版圖面風險", "報價單號", "報價行號", "報價版本", "報價日期", "客戶代碼",
         "成品編號", "規格圖面版次", "報價數量", "計價單位", "幣別", "稅別", "報價單價", "成交狀態",
         "來源檔案", "來源工作表", "來源Excel列號"]


@dataclass
class SearchResult:
    candidates: pd.DataFrame
    status: str
    message: str
    stats: dict | None
    summary: dict = field(default_factory=dict)
    query: dict = field(default_factory=dict)


def _median(values: list[Decimal]) -> Decimal:
    s = sorted(values)
    mid = len(s) // 2
    return s[mid] if len(s) % 2 else (s[mid - 1] + s[mid]) / 2


def search_similar_quotes(records: pd.DataFrame, product: str, quantity, as_of: dt.date, unit: str,
                          drawing_version: str | None = None, customer: str | None = None) -> SearchResult:
    if is_blank(product) or is_blank(unit):
        raise ValueError("成品編號與計價單位都必須填寫")
    qty = parse_number(quantity)
    if qty is None or qty <= 0:
        raise ValueError("比較數量必須是大於 0 的數字")
    if isinstance(as_of, dt.datetime):
        as_of = as_of.date()
    product, unit = str(product).strip(), str(unit).strip()
    version = None if is_blank(drawing_version) else str(drawing_version).strip()
    customer = None if is_blank(customer) else str(customer).strip()
    earliest = as_of - dt.timedelta(days=MAX_AGE_DAYS)
    query = {"成品編號": product, "比較數量": qty, "試算日": as_of, "計價單位": unit,
             "圖面版次": version, "客戶代碼": customer}

    rows = []
    for r in records.to_dict("records"):
        if r["成品編號"] != product:
            continue
        reasons, notes = [], []
        if r["最新版本"] is False:
            reasons.append("非最新版本（同單號行號有較新版本）")
        elif r["最新版本"] is None:
            reasons.append("版本先後無法判斷")
        if not r["可直接比較"]:
            reasons.append(f"不可直接比較：{r['無法比較原因']}")
        if r["計價單位"] != unit:
            reasons.append(f"計價單位不同（{r['計價單位']}）")
        hist_ver = r.get("規格圖面版次")
        risk = False
        if version is None:
            notes.append("未指定圖面版次")
        elif is_blank(hist_ver):
            notes.append("版次未知")
            risk = True
        elif hist_ver != version:
            reasons.append(f"圖面版次不同（{hist_ver}，舊版圖面風險）")
            risk = True
        if not (qty * QTY_LOW <= r["報價數量"] <= qty * QTY_HIGH):
            reasons.append(f"數量級距不同（{r['報價數量']}，可比較範圍 {qty * QTY_LOW}～{qty * QTY_HIGH}）")
        day = r["報價日期"].date()
        if day > as_of:
            reasons.append("報價日期晚於試算日")
        elif day < earliest:
            reasons.append(f"報價日期超過 {MAX_AGE_DAYS} 天")
        included = not reasons
        grade = (GRADE_A if version is not None and hist_ver == version else GRADE_B) if included else None
        out = {c: r.get(c) for c in SHOWN}
        out.update({
            "判定": INCLUDED if included else EXCLUDED, "等級": grade,
            "原因": "；".join(reasons) if reasons else ("符合全部條件" + ("；" + "；".join(notes) if notes else "")),
            "同客戶": customer is not None and r["客戶代碼"] == customer,
            "舊版圖面風險": risk,
        })
        rows.append(out)

    rows.sort(key=lambda r: (r["判定"] != INCLUDED, -r["報價日期"].toordinal()))
    candidates = pd.DataFrame(rows, columns=SHOWN, dtype=object)
    inc = [r for r in rows if r["判定"] == INCLUDED]
    summary = {"候選筆數": len(rows), "選入筆數": len(inc), "排除筆數": len(rows) - len(inc),
               "A級": sum(r["等級"] == GRADE_A for r in inc), "B級": sum(r["等級"] == GRADE_B for r in inc)}

    if not rows:
        return SearchResult(candidates, INSUFFICIENT, f"歷史資料不足：沒有成品「{product}」的歷史報價", None, summary, query)
    if len(inc) < MIN_COMPARABLE:
        return SearchResult(candidates, INSUFFICIENT,
                            f"歷史資料不足：可比較報價只有 {len(inc)} 筆（至少需要 {MIN_COMPARABLE} 筆），不提供參考區間",
                            None, summary, query)
    prices = [r["報價單價"] for r in inc]
    latest = max(inc, key=lambda r: r["報價日期"])
    stats = {
        "筆數": len(inc), "最低": min(prices), "中位數": _median(prices), "最高": max(prices),
        "最近一筆單價": latest["報價單價"], "最近一筆日期": latest["報價日期"].date(),
        "成交筆數": sum(r["成交狀態"] == "成交" for r in inc),
        "未成交筆數": sum(r["成交狀態"] == "未成交" for r in inc),
        "成交狀態未知筆數": sum(r["成交狀態"] == "未知" for r in inc),
        "同客戶筆數": sum(r["同客戶"] for r in inc),
        "舊版圖面風險筆數": sum(r["舊版圖面風險"] for r in inc),
    }
    message = (f"可比較報價 {len(inc)} 筆：最低 {stats['最低']}、中位數 {stats['中位數']}、最高 {stats['最高']}。"
               "歷史報價不是成交價，僅供參考")
    return SearchResult(candidates, REFERENCE_OK, message, stats, summary, query)
