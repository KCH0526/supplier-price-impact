"""Benchmark: historical quote import + search + advice + report with synthetic data.

    python benchmarks/run_quote_memory_benchmark.py 25000

Two files of N rows each (2N total), 500 products, one query.
"""

from __future__ import annotations

import datetime as dt
import io
import json
import resource
import sys
import time
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import openpyxl  # noqa: E402

from core.historical_quotes import HIST_REQUIRED, HistoricalSource, import_historical_quotes  # noqa: E402
from core.quote_advisor import advise_quote  # noqa: E402
from core.quote_memory_report import build_quote_memory_report  # noqa: E402
from core.quote_search import search_similar_quotes  # noqa: E402


def make(n: int, offset: int) -> bytes:
    wb = openpyxl.Workbook(write_only=True)
    ws = wb.create_sheet("HistoricalQuotes")
    ws.append(HIST_REQUIRED)
    for i in range(n):
        ws.append([f"Q-{offset + i:07d}", "1", dt.datetime(2025, 1, 1) + dt.timedelta(days=i % 600),
                   f"C-{i % 50:03d}", f"P-{i % 500:04d}", 50 + i % 40, "pcs", "TWD", 900 + i % 300, "未稅"])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def main(n: int) -> dict:
    files = [make(n, 0), make(n, n)]
    t = {}
    s = time.perf_counter()
    imp = import_historical_quotes([HistoricalSource(f"f{i}.xlsx", d, "HistoricalQuotes") for i, d in enumerate(files)])
    t["import"] = time.perf_counter() - s
    s = time.perf_counter()
    search = search_similar_quotes(imp.records, "P-0001", 60, dt.date(2026, 12, 1), "pcs")
    t["search"] = time.perf_counter() - s
    s = time.perf_counter()
    advice = advise_quote(search, imp.records, None, Decimal("0.15"), price_increase_date=dt.date(2026, 6, 1))
    t["advise"] = time.perf_counter() - s
    s = time.perf_counter()
    report = build_quote_memory_report(advice, imp)
    t["report"] = time.perf_counter() - s
    return {"rows": 2 * n, "records": len(imp.records), "candidates": len(search.candidates),
            "included": search.summary["選入筆數"], "seconds": {k: round(v, 2) for k, v in t.items()},
            "peak_rss_mb": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1),
            "report_kb": len(report) // 1024}


if __name__ == "__main__":
    print(json.dumps(main(int(sys.argv[1]) if len(sys.argv) > 1 else 25000), ensure_ascii=False))
