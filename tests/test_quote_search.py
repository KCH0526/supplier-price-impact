"""PR #17: explainable similar-quote search (spec section 5). Expected values are hand-derived."""

import datetime as dt
import io
import json
from decimal import Decimal
from pathlib import Path

import openpyxl
import pytest

from core.historical_quotes import HIST_REQUIRED, HistoricalSource, import_historical_quotes
from core.quote_search import (
    GRADE_A,
    GRADE_B,
    INCLUDED,
    EXCLUDED,
    INSUFFICIENT,
    MIN_COMPARABLE,
    REFERENCE_OK,
    search_similar_quotes,
)

ROOT = Path(__file__).resolve().parents[1]
HIST = ROOT / "samples" / "historical"


@pytest.fixture(scope="module")
def records():
    sources = []
    for name, file in (("sales_dept", "historical_quotes_sales_dept.xlsx"),
                       ("legacy_system", "historical_quotes_legacy_system.xlsx")):
        m = json.loads((HIST / f"mapping_{name}.json").read_text(encoding="utf-8"))["targets"]["HistoricalQuotes"]
        sources.append(HistoricalSource(file, (HIST / file).read_bytes(), m["source_sheet"], m["columns"]))
    result = import_historical_quotes(sources)
    assert len(result.records) == 15
    return result.records


def _records(rows):
    """rows: (單號, 日期, 客戶, 數量, 單價[, 版次[, 單位]])."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "HistoricalQuotes"
    ws.append(HIST_REQUIRED + ["規格圖面版次", "成交狀態"])
    for r in rows:
        no, date, cust, qty, price = r[:5]
        ver = r[5] if len(r) > 5 else "B"
        unit = r[6] if len(r) > 6 else "pcs"
        deal = r[7] if len(r) > 7 else None
        ws.append([no, "1", date, cust, "P-9", qty, unit, "TWD", price, "未稅", ver, deal])
    buf = io.BytesIO()
    wb.save(buf)
    return import_historical_quotes([HistoricalSource("t.xlsx", buf.getvalue(), "HistoricalQuotes")]).records


def _by_no(result):
    """Index by quote number; when a quote has several revisions, the included one wins."""
    out = {}
    for r in result.candidates.to_dict("records"):
        if r["報價單號"] not in out or r["判定"] == INCLUDED:
            out[r["報價單號"]] = r
    return out


D = dt.datetime


# ---------- sample data ----------

def test_threshold_is_three():
    assert MIN_COMPARABLE == 3


def test_sample_with_drawing_b_has_insufficient_history(records):
    res = search_similar_quotes(records, "P-1001", 60, dt.date(2026, 12, 1), "pcs", drawing_version="B")
    c = _by_no(res)
    assert {n for n, r in c.items() if r["判定"] == INCLUDED} == {"Q-2603-007", "Q-2609-021"}
    assert res.status == INSUFFICIENT and res.stats is None
    assert "歷史資料不足" in res.message and "2" in res.message
    # every exclusion has its reason
    assert "圖面版次不同" in c["Q-2501-001"]["原因"]
    assert "USD" in c["Q-2610-030"]["原因"]
    assert "含稅" in c["Q-2610-031"]["原因"]
    assert "計價單位不同" in c["Q-2611-001"]["原因"]
    assert "晚於試算日" in c["Q-2612-002"]["原因"]
    assert "數量級距不同" in c["Q-2512-009"]["原因"]
    assert "超過 730 天" in c["Q-2311-003"]["原因"]
    old = [r for r in res.candidates.to_dict("records") if r["報價單號"] == "Q-2603-007" and r["報價版本"] == "1"][0]
    assert old["判定"] == EXCLUDED and "非最新版本" in old["原因"]
    assert set(res.candidates["成品編號"]) == {"P-1001"}  # other products never listed
    assert res.summary == {"候選筆數": 11, "選入筆數": 2, "排除筆數": 9, "A級": 2, "B級": 0}


def test_sample_with_drawing_b_after_new_quote(records):
    res = search_similar_quotes(records, "P-1001", 60, dt.date(2026, 12, 15), "pcs", drawing_version="B",
                                customer="C-001")
    assert res.status == REFERENCE_OK
    s = res.stats
    assert (s["筆數"], s["最低"], s["中位數"], s["最高"]) == (3, Decimal("990"), Decimal("1050"), Decimal("1050"))
    assert s["最近一筆單價"] == Decimal("1050") and s["最近一筆日期"] == dt.date(2026, 12, 10)
    assert s["成交筆數"] == 2 and s["成交狀態未知筆數"] == 1 and s["同客戶筆數"] == 2
    c = _by_no(res)
    assert c["Q-2612-002"]["同客戶"] is True and c["Q-2609-021"]["同客戶"] is False
    assert {c[n]["等級"] for n in ("Q-2603-007", "Q-2609-021", "Q-2612-002")} == {GRADE_A}


def test_without_drawing_version_matches_are_grade_b(records):
    res = search_similar_quotes(records, "P-1001", 60, dt.date(2026, 12, 1), "pcs")
    inc = {r["報價單號"]: r for r in res.candidates.to_dict("records") if r["判定"] == INCLUDED}
    assert set(inc) == {"Q-2501-001", "Q-2506-014", "Q-2603-007", "Q-2609-021"}
    assert {r["等級"] for r in inc.values()} == {GRADE_B}
    assert all("未指定圖面版次" in r["原因"] for r in inc.values())
    # 950, 980, 990, 1050 -> median (980 + 990) / 2 = 985
    assert res.stats["中位數"] == Decimal("985") and res.stats["最低"] == Decimal("950")
    assert res.stats["舊版圖面風險筆數"] == 0


def test_unknown_product_returns_no_candidates(records):
    res = search_similar_quotes(records, "P-0000", 10, dt.date(2026, 12, 1), "pcs")
    assert res.candidates.empty and res.status == INSUFFICIENT and res.stats is None
    assert "沒有" in res.message


# ---------- rules in isolation ----------

def test_quantity_band_bounds_are_inclusive():
    recs = _records([("Q1", D(2026, 1, 1), "C", 50, 100), ("Q2", D(2026, 1, 1), "C", 200, 100),
                     ("Q3", D(2026, 1, 1), "C", 49, 100), ("Q4", D(2026, 1, 1), "C", 201, 100)])
    c = _by_no(search_similar_quotes(recs, "P-9", 100, dt.date(2026, 6, 1), "pcs", drawing_version="B"))
    assert [c[n]["判定"] for n in ("Q1", "Q2", "Q3", "Q4")] == [INCLUDED, INCLUDED, EXCLUDED, EXCLUDED]


def test_date_window_730_days_inclusive_and_no_future_quotes():
    as_of = dt.date(2026, 12, 1)
    recs = _records([("Q1", D(2024, 12, 1), "C", 10, 100), ("Q2", D(2024, 11, 30), "C", 10, 100),
                     ("Q3", D(2026, 12, 1), "C", 10, 100), ("Q4", D(2026, 12, 2), "C", 10, 100)])
    c = _by_no(search_similar_quotes(recs, "P-9", 10, as_of, "pcs", drawing_version="B"))
    assert [c[n]["判定"] for n in ("Q1", "Q2", "Q3", "Q4")] == [INCLUDED, EXCLUDED, INCLUDED, EXCLUDED]


def test_drawing_version_blank_is_grade_b_with_warning_and_different_is_excluded():
    recs = _records([("Q1", D(2026, 1, 1), "C", 10, 100, "B"), ("Q2", D(2026, 1, 1), "C", 10, 110, None),
                     ("Q3", D(2026, 1, 1), "C", 10, 90, "A"), ("Q4", D(2026, 1, 1), "C", 10, 105, "B")])
    res = search_similar_quotes(recs, "P-9", 10, dt.date(2026, 6, 1), "pcs", drawing_version="B")
    c = _by_no(res)
    assert (c["Q1"]["等級"], c["Q2"]["等級"], c["Q3"]["判定"]) == (GRADE_A, GRADE_B, EXCLUDED)
    assert "版次未知" in c["Q2"]["原因"] and c["Q2"]["舊版圖面風險"] is True
    assert c["Q3"]["舊版圖面風險"] is True
    assert res.stats["舊版圖面風險筆數"] == 1  # among included rows: Q2


def test_same_and_other_customers_are_both_used_and_flagged():
    recs = _records([("Q1", D(2026, 1, 1), "C-1", 10, 100), ("Q2", D(2026, 2, 1), "C-2", 10, 120),
                     ("Q3", D(2026, 3, 1), "C-3", 10, 110)])
    res = search_similar_quotes(recs, "P-9", 10, dt.date(2026, 6, 1), "pcs", drawing_version="B", customer="C-2")
    c = _by_no(res)
    assert [c[n]["同客戶"] for n in ("Q1", "Q2", "Q3")] == [False, True, False]
    assert res.stats["同客戶筆數"] == 1 and res.stats["中位數"] == Decimal("110")


def test_all_expired_gives_insufficient_and_no_range():
    recs = _records([("Q1", D(2020, 1, 1), "C", 10, 100), ("Q2", D(2020, 2, 1), "C", 10, 100),
                     ("Q3", D(2020, 3, 1), "C", 10, 100)])
    res = search_similar_quotes(recs, "P-9", 10, dt.date(2026, 6, 1), "pcs")
    assert res.status == INSUFFICIENT and res.stats is None
    assert res.summary["選入筆數"] == 0


def test_unknown_deal_status_is_never_counted_as_won():
    recs = _records([("Q1", D(2026, 1, 1), "C", 10, 100, "B", "pcs", "成交"),
                     ("Q2", D(2026, 1, 2), "C", 10, 100, "B", "pcs", None),
                     ("Q3", D(2026, 1, 3), "C", 10, 100, "B", "pcs", "未成交")])
    s = search_similar_quotes(recs, "P-9", 10, dt.date(2026, 6, 1), "pcs").stats
    assert (s["成交筆數"], s["未成交筆數"], s["成交狀態未知筆數"]) == (1, 1, 1)


def test_invalid_query_inputs_are_rejected(records):
    for kwargs in ({"quantity": 0}, {"quantity": -1}, {"unit": ""}, {"product": " "}):
        args = {"product": "P-1001", "quantity": 10, "as_of": dt.date(2026, 1, 1), "unit": "pcs"} | kwargs
        with pytest.raises(ValueError):
            search_similar_quotes(records, **args)
