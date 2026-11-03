"""Real Streamlit widget-flow tests, including uploaded XLSX files."""

from io import BytesIO
from pathlib import Path

import openpyxl
import pytest

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]
TITLE = "供應商漲價與客戶報價毛利風險覆核器"
BUTTON = "產生毛利風險報告"


def _app():
    app = AppTest.from_file(str(ROOT / "app.py"), default_timeout=30).run()
    assert not app.exception
    assert app.title[0].value == TITLE
    return app


def _upload(app, quotes=True):
    app.file_uploader[0].upload("sample_bom.xlsx", (ROOT / "samples" / "sample_bom.xlsx").read_bytes())
    app.file_uploader[1].upload("sample_price_increase.xlsx",
                                (ROOT / "samples" / "sample_price_increase.xlsx").read_bytes())
    if quotes:
        app.file_uploader[2].upload("sample_open_quotes.xlsx",
                                    (ROOT / "samples" / "sample_open_quotes.xlsx").read_bytes())
    app.run()
    assert not app.exception


def _button(app):
    return next(b for b in app.button if b.label == BUTTON)


def test_three_file_flow_produces_quote_risk_report():
    app = _app()
    assert len(app.file_uploader) == 3
    assert app.number_input[0].value == 15.0  # default floor in percent
    _upload(app)
    _button(app).click().run()
    assert not app.exception
    assert len(app.download_button) == 1
    wb = openpyxl.load_workbook(BytesIO(app.session_state["latest_report"]["file"]), data_only=True)
    assert wb.sheetnames == ["Summary", "Cost Impact", "Exceptions", "Line Audit", "Quote Risk", "Quote Exceptions"]
    summary = dict(wb["Summary"].values)
    assert summary["預估每月總成本增加（TWD）"] == 61597
    assert summary["客戶報價：需人工覆核"] == 3
    assert wb["Quote Risk"].max_row == 9
    texts = " ".join(m.value for m in app.markdown) + " ".join(c.value for c in app.caption)
    assert "依報價數量推估的情境金額" in texts


def test_changing_floor_changes_review_count():
    app = _app()
    _upload(app)
    app.number_input[0].set_value(13.0).run()
    _button(app).click().run()
    assert not app.exception
    wb = openpyxl.load_workbook(BytesIO(app.session_state["latest_report"]["file"]), data_only=True)
    summary = dict(wb["Summary"].values)
    assert summary["客戶報價：最低毛利率底線"] == "13.00%"
    # New margins: P-1001/C-001 12.78% and P-1003 11.56% are below 13%;
    # P-1005 14.43% is not.
    assert summary["客戶報價：需人工覆核"] == 2


def test_two_file_flow_still_produces_cost_report():
    app = _app()
    _upload(app, quotes=False)
    _button(app).click().run()
    assert not app.exception
    wb = openpyxl.load_workbook(BytesIO(app.session_state["latest_report"]["file"]), data_only=True)
    assert wb.sheetnames == ["Summary", "Cost Impact", "Exceptions", "Line Audit"]
    assert dict(wb["Summary"].values)["預估每月總成本增加（TWD）"] == 61597
