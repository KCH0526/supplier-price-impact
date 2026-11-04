"""End-to-end performance benchmark with synthetic data.

    python benchmarks/run_benchmark.py 1000 10000 20000 50000

Each size runs in a fresh subprocess so peak memory is per size (Linux/macOS: ru_maxrss;
Windows: PeakWorkingSetSize).
N = number of BOM lines; the price file has N/2 rows and OpenQuotes N/10 rows
(both capped at the 50,000-row sheet limit). Data is fully synthetic.
"""

from __future__ import annotations

import datetime as dt
import io
import json
import platform
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

AS_OF = dt.date(2026, 12, 1)
D1, D2 = dt.datetime(2026, 11, 1), dt.datetime(2027, 1, 31)


def make_inputs(n: int) -> tuple[bytes, bytes, bytes]:
    import openpyxl

    from core.quote_reader import QUOTE_REQUIRED_COLUMNS
    from core.validation import BOM_REQUIRED_COLUMNS, PRICE_REQUIRED_COLUMNS

    products = max(1, n // 10)

    def book(sheets):
        wb = openpyxl.Workbook(write_only=True)
        for name, header, rows in sheets:
            ws = wb.create_sheet(name)
            ws.append(header)
            for r in rows:
                ws.append(r)
        buf = io.BytesIO()
        wb.save(buf)
        return buf.getvalue()

    bom_rows = ([f"P-{i % products:06d}", "成品", f"M-{i:07d}", "材料", "pcs", 2, 10.5] for i in range(n))
    cost_rows = ([f"P-{p:06d}", 100, 50, 0, "TWD", 1000] for p in range(products))
    bom = book([("BOM", BOM_REQUIRED_COLUMNS, bom_rows),
                ("ProductCost", ["成品編號", "單件人工成本", "單件製造費用", "單件其他成本", "銷售幣別", "預估月產量"],
                 cost_rows)])
    price = book([("PriceIncrease", PRICE_REQUIRED_COLUMNS,
                   ([f"M-{i:07d}", "材料", "pcs", "TWD", 11.25, D1] for i in range(0, n, 2)))])
    q = min(50_000, max(1, n // 10))
    quotes = book([("OpenQuotes", QUOTE_REQUIRED_COLUMNS,
                    ([f"Q-{i:07d}", "1", f"P-{i % products:06d}", "C-001", 900, "TWD", 10, D1, D2, "有效"]
                     for i in range(q)))])
    return bom, price, quotes


def peak_rss_mb() -> float:
    """Peak resident memory of this process in MB, standard library only, on Linux, macOS and Windows."""
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        class Counters(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                        ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                        ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]
        c = Counters()
        c.cb = ctypes.sizeof(c)
        get_info = ctypes.WinDLL("psapi").GetProcessMemoryInfo
        get_info.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
        if not get_info(ctypes.windll.kernel32.GetCurrentProcess(), ctypes.byref(c), c.cb):
            raise OSError("GetProcessMemoryInfo failed")
        return round(c.PeakWorkingSetSize / 1024 / 1024, 1)
    import resource
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    # ru_maxrss is in bytes on macOS and in kilobytes on Linux.
    return round(peak / 1024 / 1024 if sys.platform == "darwin" else peak / 1024, 1)


def run_once(n: int) -> dict:
    from decimal import Decimal

    from core.calculator import calculate_cost_impact
    from core.matcher import match_prices
    from core.quote_reader import read_open_quotes
    from core.quote_risk import assess_quote_risk
    from core.reader import read_bom, read_price_increase, read_sheet
    from core.report import build_report

    bom_b, price_b, quote_b = make_inputs(n)
    t = {}
    start = time.perf_counter()
    bom, price = read_bom(bom_b), read_price_increase(price_b)
    quotes, pc = read_open_quotes(quote_b), read_sheet(bom_b, "ProductCost", ["成品編號"])
    t["read"] = time.perf_counter() - start
    errors = [i.reason for r in (bom, price, quotes, pc) for i in r.issues]
    if errors:
        return {"n": n, "error": errors[:3]}
    s = time.perf_counter(); matched = match_prices(bom.data, price.data, AS_OF); t["match"] = time.perf_counter() - s
    s = time.perf_counter(); costs = calculate_cost_impact(matched, pc.data); t["calculate"] = time.perf_counter() - s
    s = time.perf_counter(); risk = assess_quote_risk(quotes.data, costs, AS_OF, Decimal("0.15")); t["quote_risk"] = time.perf_counter() - s
    s = time.perf_counter(); report = build_report(matched, costs, AS_OF, risk); t["export"] = time.perf_counter() - s
    return {
        "n": n,
        "bytes_in": len(bom_b) + len(price_b) + len(quote_b),
        "seconds": {k: round(v, 2) for k, v in t.items()},
        "total_seconds": round(sum(t.values()), 2),
        "peak_rss_mb": peak_rss_mb(),
        "report_mb": round(len(report) / 1024 / 1024, 2),
        "complete_products": costs.summary["可完整試算成品數"],
        "products": costs.summary["總成品數"],
        "exceptions": len(matched.exceptions),
        "quotes_review": risk.summary["需人工覆核"],
        "quotes": len(quotes.data),
    }


def main(sizes):
    env = {"python": platform.python_version(), "platform": platform.platform(),
           "cpu_count": __import__("os").cpu_count()}
    print(json.dumps({"environment": env}, ensure_ascii=False))
    for n in sizes:
        out = subprocess.run([sys.executable, __file__, "--one", str(n)], capture_output=True, text=True)
        print(out.stdout.strip() if out.returncode == 0 else json.dumps({"n": n, "error": out.stderr[-500:]}))


if __name__ == "__main__":
    if sys.argv[1:2] == ["--one"]:
        print(json.dumps(run_once(int(sys.argv[2])), ensure_ascii=False))
    else:
        main([int(a) for a in sys.argv[1:]] or [1000, 10000, 20000, 50000])
