"""Rebuild demo/quote_recommendation_example.xlsx from synthetic data.

    python demo/build_quote_recommendation_example.py

Historical quotes: samples/historical/ (two files, each with its mapping).
Cost: samples/sample_bom.xlsx + samples/sample_price_increase.xlsx.
Query: P-1001, 60 pcs, drawing B, as-of 2026-12-15, target margin 15%,
supplier price change effective 2026-12-01.
"""

from __future__ import annotations

import datetime as dt
import json
import sys
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.calculator import calculate_cost_impact  # noqa: E402
from core.historical_quotes import HistoricalSource, import_historical_quotes  # noqa: E402
from core.matcher import match_prices  # noqa: E402
from core.quote_advisor import advise_quote  # noqa: E402
from core.quote_memory_report import build_quote_memory_report  # noqa: E402
from core.quote_search import search_similar_quotes  # noqa: E402
from core.reader import read_bom, read_price_increase, read_sheet  # noqa: E402

HIST = ROOT / "samples" / "historical"
OUTPUT = ROOT / "demo" / "quote_recommendation_example.xlsx"
AS_OF, INCREASE = dt.date(2026, 12, 15), dt.date(2026, 12, 1)


def import_samples():
    sources = []
    for name, file in (("sales_dept", "historical_quotes_sales_dept.xlsx"),
                       ("legacy_system", "historical_quotes_legacy_system.xlsx")):
        m = json.loads((HIST / f"mapping_{name}.json").read_text(encoding="utf-8"))["targets"]["HistoricalQuotes"]
        sources.append(HistoricalSource(file, (HIST / file).read_bytes(), m["source_sheet"], m["columns"]))
    return import_historical_quotes(sources)


def build_standardized_history() -> bytes:
    """Standardized historical quotes for the 報價工作台 demo (re-importable)."""
    from core.historical_quotes import build_historical_workbook
    return build_historical_workbook(import_samples().records)


def build() -> bytes:
    imported = import_samples()
    bom = ROOT / "samples" / "sample_bom.xlsx"
    matched = match_prices(read_bom(bom).data, read_price_increase(ROOT / "samples" / "sample_price_increase.xlsx").data,
                           AS_OF)
    costs = calculate_cost_impact(matched, read_sheet(bom, "ProductCost", ["成品編號"]).data)
    search = search_similar_quotes(imported.records, "P-1001", 60, AS_OF, "pcs", drawing_version="B")
    advice = advise_quote(search, imported.records, costs, Decimal("0.15"), price_increase_date=INCREASE)
    return build_quote_memory_report(advice, imported)


if __name__ == "__main__":
    OUTPUT.write_bytes(build())
    (ROOT / "demo" / "historical_quotes_standardized_demo.xlsx").write_bytes(build_standardized_history())
    print(f"wrote {OUTPUT.relative_to(ROOT)} and demo/historical_quotes_standardized_demo.xlsx")
