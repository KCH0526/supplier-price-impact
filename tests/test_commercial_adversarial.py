"""PR #26: cross-feature adversarial checks for the commercial quoting workflow."""

import datetime as dt
import io
from decimal import Decimal
from pathlib import Path

import openpyxl
import pytest

from core.batch_cost import MODE_DETAILED, MODE_EXISTING, CostModel, cost_model_for, read_batch_costs
from core.customer_draft import build_customer_draft, build_customer_draft_workbook
from core.quantity_tiers import compute_quantity_tiers
from core.workbench_report import build_workbench_report

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]


def _cells(content):
    wb = openpyxl.load_workbook(io.BytesIO(content))
    return wb, [c for ws in wb for row in ws.iter_rows() for c in row]


def test_draft_from_workbench_with_history_loaded_has_no_other_customers():
    from tests.test_workbench import _btn, _manual_tiers, _page
    app = _page()
    app.file_uploader(key="hist_std").upload("hist.xlsx", (ROOT / "demo" / "historical_quotes_standardized_demo.xlsx").read_bytes()).run()
    _manual_tiers(app)
    app.text_input(key="d_customer").set_value("C-001").run()
    app.text_input(key="d_quote_no").set_value("SQ-X").run()
    for q, p in ((10, "420"), (100, "250"), (500, "235")):
        app.text_input(key=f"d_price_{q}").set_value(p).run()
    app.checkbox(key="d_confirmed").check().run()
    _btn(app, "產生客戶報價草稿").click().run()
    _, cells = _cells(app.session_state["draft"]["file"])
    text = " ".join(str(c.value) for c in cells if c.value is not None)
    for other in ("C-002", "C-003", "C-004", "C-005", "C-006", "00125", "Q-26", "990", "1050"):
        assert other not in text, other
    assert "報價草稿（價格已人工填寫" in text
    # the internal report may carry history; it is a different file
    internal, _ = _cells(app.session_state["tiers"]["report"])
    assert "Quantity Tiers" in internal.sheetnames


def test_internal_report_text_is_formula_safe():
    model = CostModel('=HYPERLINK("http://example.invalid")', MODE_DETAILED, True, unit_variable=Decimal("1"),
                      batch_fixed=Decimal("1"), basis="@SUM(A1)", source="+cmd")
    content = build_workbench_report(compute_quantity_tiers(model, [1], "0.1"))
    _, cells = _cells(content)
    assert not [c for c in cells if c.data_type == "f"]


def test_existing_mode_never_double_counts_even_if_batch_data_exists():
    table = read_batch_costs(ROOT / "samples" / "batch_cost" / "batch_cost_sample.xlsx")
    existing = CostModel("P-1001", MODE_EXISTING, True, unit_variable=Decimal("872.20"), batch_fixed=None)
    rows = compute_quantity_tiers(existing, [10, 1000], "0.15").rows
    assert list(rows["安全底價（試算）"]) == [Decimal("1026.12"), Decimal("1026.12")]
    detailed = cost_model_for("P-1001", MODE_DETAILED, dt.date(2026, 12, 1), batch=table, version="B")
    rows = compute_quantity_tiers(detailed, [10], "0.15").rows      # (890 + 1800/10) / 0.85 = 1258.82...
    assert rows.iloc[0]["安全底價（試算）"] == Decimal("1258.83")


def test_floor_never_below_margin_for_many_quantities():
    model = CostModel("P", MODE_DETAILED, True, unit_variable=Decimal("180"), batch_fixed=Decimal("1500"))
    rows = compute_quantity_tiers(model, list(range(1, 21)), "0.2").rows
    for r in rows.to_dict("records"):
        price = r["安全底價（試算）"]
        assert (price - r["每件情境成本"]) / price >= Decimal("0.2")
        assert price == price.quantize(Decimal("0.01"))


def test_customer_draft_price_is_never_derived_from_floor():
    draft = build_customer_draft({"客戶代碼": "C-1"}, [{"成品編號": "P", "數量": 10, "計價單位": "pcs", "幣別": "TWD",
                                                     "安全底價（試算）": Decimal("412.50")}], prices_confirmed=True)
    assert draft.lines[0]["報價單價"] is None and draft.label == "未核准草稿"
    _, cells = _cells(build_customer_draft_workbook(draft))
    assert not [c for c in cells if c.value in (412.5, 0)]
