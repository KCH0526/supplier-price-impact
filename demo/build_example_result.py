"""Rebuild demo/example_result.xlsx from the three synthetic samples.

    python demo/build_example_result.py

As-of date 2026-12-01, minimum margin 15%. Uses exactly the same code path
as the web page, so the file shows what a user downloads.
"""

from __future__ import annotations

import datetime as dt
import sys
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.calculator import calculate_cost_impact  # noqa: E402
from core.matcher import match_prices  # noqa: E402
from core.quote_reader import read_open_quotes  # noqa: E402
from core.quote_risk import assess_quote_risk  # noqa: E402
from core.reader import read_bom, read_price_increase, read_sheet  # noqa: E402
from core.report import build_report  # noqa: E402

AS_OF = dt.date(2026, 12, 1)
MIN_MARGIN = Decimal("0.15")
INPUTS = {
    "bom": ROOT / "samples" / "sample_bom.xlsx",
    "price": ROOT / "samples" / "sample_price_increase.xlsx",
    "quotes": ROOT / "samples" / "sample_open_quotes.xlsx",
}
OUTPUT = ROOT / "demo" / "example_result.xlsx"


def build() -> bytes:
    matched = match_prices(read_bom(INPUTS["bom"]).data, read_price_increase(INPUTS["price"]).data, AS_OF)
    costs = calculate_cost_impact(matched, read_sheet(INPUTS["bom"], "ProductCost", ["成品編號"]).data)
    risk = assess_quote_risk(read_open_quotes(INPUTS["quotes"]).data, costs, AS_OF, MIN_MARGIN)
    return build_report(matched, costs, AS_OF, risk)


if __name__ == "__main__":
    OUTPUT.write_bytes(build())
    print(f"wrote {OUTPUT.relative_to(ROOT)}")
