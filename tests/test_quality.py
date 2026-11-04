"""PR #14 quality checks not covered elsewhere, plus a benchmark smoke test."""

import datetime as dt
import importlib.util
import io
from decimal import Decimal
from pathlib import Path

import openpyxl
import pandas as pd

from core.calculator import calculate_cost_impact
from core.matcher import match_prices
from core.report import build_report
from core.validation import BOM_REQUIRED_COLUMNS, PRICE_REQUIRED_COLUMNS

ROOT = Path(__file__).resolve().parents[1]
AS_OF = dt.date(2026, 12, 1)


def _frame(columns, rows):
    df = pd.DataFrame(rows, columns=columns, dtype=object)
    df.insert(0, "excel_row", range(2, 2 + len(df)))
    return df


def test_many_small_decimal_lines_sum_exactly():
    # 1,000 lines of 0.1 x 0.3 would drift with binary floats; Decimal must give exactly 30.
    bom = _frame(BOM_REQUIRED_COLUMNS, [["P-1", "p", f"M-{i}", "m", "pcs", 0.1, 0.3] for i in range(1000)])
    price = _frame(PRICE_REQUIRED_COLUMNS, [["M-0", "m", "pcs", "TWD", 0.7, dt.datetime(2026, 12, 1)]])
    costs = calculate_cost_impact(match_prices(bom, price, AS_OF), None)
    row = costs.cost_impact.iloc[0]
    assert row["原材料成本"] == Decimal("30.0")
    assert row["新材料成本"] == Decimal("30.04")
    assert row["成本增加"] == Decimal("0.04")
    assert sum([0.1 * 0.3] * 1000) != 30.0  # the float version is indeed wrong


def test_leading_zero_ids_survive_to_the_exported_report():
    bom = _frame(BOM_REQUIRED_COLUMNS, [["000123", "p", "0045", "m", "pcs", 1, 10]])
    price = _frame(PRICE_REQUIRED_COLUMNS, [["0045", "m", "pcs", "TWD", 11, dt.datetime(2026, 12, 1)]])
    matched = match_prices(bom, price, AS_OF)
    costs = calculate_cost_impact(matched, None)
    wb = openpyxl.load_workbook(io.BytesIO(build_report(matched, costs, AS_OF)), data_only=True)
    impact = wb["Cost Impact"]
    assert impact.cell(2, 1).value == "000123" and impact.cell(2, 1).number_format == "@"
    audit = [r for r in wb["Line Audit"].iter_rows(min_row=2, values_only=True)][0]
    assert audit[0] == "000123" and audit[2] == "0045"


def test_benchmark_smoke_run_is_consistent():
    spec = importlib.util.spec_from_file_location("bench", ROOT / "benchmarks" / "run_benchmark.py")
    bench = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bench)
    result = bench.run_once(300)
    assert "error" not in result
    assert result["products"] == result["complete_products"] == 30
    assert result["exceptions"] == 0 and result["quotes"] == 30
    assert set(result["seconds"]) == {"read", "match", "calculate", "quote_risk", "export"}
    # Peak memory is measured on Linux, macOS and Windows (stdlib only); a Python process
    # that has loaded pandas uses tens of MB, never less than 1 MB or more than 64 GB.
    assert 1 < result["peak_rss_mb"] < 65536


def test_report_generation_shows_a_progress_indicator():
    # 50,000 BOM lines take about 40 seconds; users must see that work is in progress.
    import ast

    tree = ast.parse((ROOT / "app.py").read_text(encoding="utf-8"))
    spinners = [n for n in ast.walk(tree) if isinstance(n, ast.With)
                and any(getattr(getattr(i.context_expr, "func", None), "attr", "") == "spinner" for i in n.items)]
    assert spinners, "app.py must wrap report generation in st.spinner"
    calls = {getattr(c.func, "id", getattr(c.func, "attr", "")) for s in spinners for c in ast.walk(s)
             if isinstance(c, ast.Call)}
    assert {"match_prices", "build_report"} <= calls
