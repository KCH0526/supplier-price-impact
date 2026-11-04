"""PR #20: adversarial checks for the quote memory module (spec sections 7-8)."""

import ast
import datetime as dt
import io
from decimal import Decimal
from pathlib import Path

import openpyxl

from core.historical_quotes import HIST_REQUIRED, HistoricalSource, import_historical_quotes
from core.quote_advisor import STATUS_NO_FLOOR, advise_quote
from core.quote_memory_report import build_quote_memory_report
from core.quote_search import INSUFFICIENT, search_similar_quotes
from tests.test_quote_advisor import INCREASE, _costs

ROOT = Path(__file__).resolve().parents[1]
D = dt.datetime


def _records(rows, extra_cols=()):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "HistoricalQuotes"
    ws.append(HIST_REQUIRED + list(extra_cols))
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return import_historical_quotes([HistoricalSource("adv.xlsx", buf.getvalue(), "HistoricalQuotes")])


def _row(no, cust, price, unit="pcs", cur="TWD", tax="未稅", qty=60, date=D(2026, 6, 1), product="P-1001"):
    return [no, "1", date, cust, product, qty, unit, cur, price, tax]


def _report(imported, customer=None, product_cost=True):
    search = search_similar_quotes(imported.records, "P-1001", 60, dt.date(2026, 12, 1), "pcs", customer=customer)
    advice = advise_quote(search, imported.records, _costs(product_cost), "0.15", price_increase_date=INCREASE)
    return advice, openpyxl.load_workbook(io.BytesIO(build_quote_memory_report(advice, imported)), data_only=True)


def _texts(ws):
    return " ".join(str(v) for row in ws.iter_rows(values_only=True) for v in row if v is not None)


# ---------- customer isolation ----------

def test_other_customers_only_appear_in_the_internal_evidence_sheet():
    imp = _records([_row("Q1", "SECRET-A", 1000), _row("Q2", "SECRET-B", 1100), _row("Q3", "C-OWN", 1050)])
    advice, wb = _report(imp, customer="C-OWN")
    for sheet in ("Summary", "Quote Recommendation", "Price Exceptions"):
        text = _texts(wb[sheet])
        assert "SECRET-A" not in text and "SECRET-B" not in text, sheet
    evidence = _texts(wb["Historical Evidence"])
    assert "SECRET-A" in evidence and "不可提供給客戶" in evidence


def test_no_customer_facing_document_is_generated():
    imp = _records([_row("Q1", "A", 1000), _row("Q2", "B", 1100), _row("Q3", "C", 1050)])
    _, wb = _report(imp)
    assert all("內部" in str(ws["A1"].value) or "僅供內部" in str(ws["A1"].value) for ws in wb)
    assert not any("報價單" in ws.title or "Customer" in ws.title for ws in wb)


# ---------- no invented numbers ----------

def test_blank_prices_never_produce_zero_or_a_range():
    imp = _records([["Q1", "1", D(2026, 6, 1), "C", "P-1001", 60, "pcs", "TWD", None, "未稅"],
                    ["Q2", "1", D(2026, 6, 1), "C", "P-1001", 60, "pcs", "TWD", 0, "未稅"]])
    assert imp.records.empty
    advice, wb = _report(imp)
    assert advice.reference is None
    rec = dict((r[0], r[1]) for r in wb["Quote Recommendation"].iter_rows(min_row=3, values_only=True))
    assert rec["歷史最低"] is None and rec["歷史中位數"] is None


def test_no_history_gives_insufficient_and_no_range():
    imp = _records([_row("Q1", "C", 1000, product="P-1002")])
    search = search_similar_quotes(imp.records, "P-1001", 60, dt.date(2026, 12, 1), "pcs")
    assert search.status == INSUFFICIENT and search.stats is None


def test_blocked_component_never_shows_a_full_margin_floor():
    edge = ROOT / "tests" / "fixtures"
    costs = _costs(product_cost=False, bom=edge / "test_bom_edge_cases.xlsx", price=edge / "test_price_edge_cases.xlsx")
    imp = _records([_row(f"Q{i}", "C", 100, product="P-X01", qty=1) for i in range(3)])
    search = search_similar_quotes(imp.records, "P-X01", 1, dt.date(2026, 12, 1), "pcs")
    advice = advise_quote(search, imp.records, costs, "0.15")
    assert advice.status == STATUS_NO_FLOOR and advice.floor["安全底價"] is None


# ---------- unit / currency / tax / deal confusion ----------

def test_unit_currency_and_tax_confusion_never_enter_statistics():
    imp = _records([_row("Q1", "C", 1000), _row("Q2", "C", 1010), _row("Q3", "C", 1020),
                    _row("Q4", "C", 5000, unit="set"), _row("Q5", "C", 30, cur="USD"), _row("Q6", "C", 1100, tax="含稅"),
                    _row("Q7", "C", 1100, tax=None)])
    s = search_similar_quotes(imp.records, "P-1001", 60, dt.date(2026, 12, 1), "pcs").stats
    assert (s["筆數"], s["最低"], s["最高"]) == (3, Decimal("1000"), Decimal("1020"))


def test_unknown_deal_status_never_counted_as_won():
    imp = _records([_row("Q1", "C", 1000) + ["成交"], _row("Q2", "C", 1000) + ["應該有吧"], _row("Q3", "C", 1000) + [None]],
                   extra_cols=["成交狀態"])
    s = search_similar_quotes(imp.records, "P-1001", 60, dt.date(2026, 12, 1), "pcs").stats
    assert (s["成交筆數"], s["成交狀態未知筆數"]) == (1, 2)


def test_revisions_and_duplicates_do_not_double_count():
    rows = [["Q1", "1", D(2026, 5, 1), "C", "P-1001", 60, "pcs", "TWD", 900, "未稅", "1"],
            ["Q1", "1", D(2026, 5, 9), "C", "P-1001", 60, "pcs", "TWD", 1000, "未稅", "2"],
            ["Q1", "1", D(2026, 5, 9), "C", "P-1001", 60, "pcs", "TWD", 1000, "未稅", "2"],
            ["Q2", "1", D(2026, 6, 1), "C", "P-1001", 60, "pcs", "TWD", 1010, "未稅", ""],
            ["Q3", "1", D(2026, 7, 1), "C", "P-1001", 60, "pcs", "TWD", 1020, "未稅", ""]]
    imp = _records(rows, extra_cols=["報價版本"])
    s = search_similar_quotes(imp.records, "P-1001", 60, dt.date(2026, 12, 1), "pcs").stats
    assert s["筆數"] == 3 and s["最低"] == Decimal("1000")  # revision 1 (900) and the duplicate are not used


# ---------- no outbound transfer, no AI claims ----------

NETWORK_MODULES = {"requests", "urllib", "urllib3", "http", "httpx", "socket", "aiohttp", "smtplib", "ftplib"}


def test_application_code_imports_no_network_libraries():
    files = [ROOT / "app.py", *(ROOT / "core").glob("*.py"), *(ROOT / "pages").glob("*.py")]
    for path in files:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names = [a.name for a in node.names] if isinstance(node, ast.Import) else \
                [node.module or ""] if isinstance(node, ast.ImportFrom) else []
            for name in names:
                assert name.split(".")[0] not in NETWORK_MODULES, f"{path.name} imports {name}"


def test_ui_and_report_do_not_present_rules_as_ai():
    for path in (ROOT / "pages" / "2_歷史報價與建議報價.py", ROOT / "core" / "quote_memory_report.py",
                 ROOT / "core" / "quote_advisor.py"):
        text = path.read_text(encoding="utf-8")
        for word in ("AI", "人工智慧", "智慧報價", "機器學習", "最佳價格"):
            assert word not in text, f"{path.name}: {word}"
