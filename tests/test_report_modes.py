"""PR #27: explicit report mode on the main page (成本影響報告 / 客戶報價風險報告)."""

import datetime as dt
import io
from pathlib import Path

import openpyxl
import pytest

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest

from core.report import REPORT_TYPE_COST, REPORT_TYPE_RISK

ROOT = Path(__file__).resolve().parents[1]
S = ROOT / "samples"
COST_BUTTON, RISK_BUTTON = "產生成本影響報告", "產生客戶報價風險報告"


def _app():
    app = AppTest.from_file(str(ROOT / "app.py"), default_timeout=30).run()
    assert not app.exception
    return app


def _upload(app, slot, name):
    app.file_uploader(key=slot).upload(name, (S / name).read_bytes()).run()


def _labels(app):
    return [b.label for b in app.button]


def _summary(content):
    return dict(openpyxl.load_workbook(io.BytesIO(content), data_only=True)["Summary"].values)


def test_mode_must_be_chosen_explicitly():
    app = _app()
    assert app.radio(key="report_mode").value is None
    assert not app.file_uploader and COST_BUTTON not in _labels(app) and RISK_BUTTON not in _labels(app)
    assert any("請先選擇報告類型" in i.value for i in app.info)


def test_cost_mode_needs_two_files_and_says_what_it_is():
    app = _app()
    app.radio(key="report_mode").set_value(REPORT_TYPE_COST).run()
    assert len(app.file_uploader) == 2
    _upload(app, "bom", "sample_bom.xlsx")
    assert COST_BUTTON not in _labels(app)
    _upload(app, "quote", "sample_price_increase.xlsx")
    next(b for b in app.button if b.label == COST_BUTTON).click().run()
    assert not app.exception
    report = app.session_state["latest_report"]
    wb = openpyxl.load_workbook(io.BytesIO(report["file"]))
    assert wb.sheetnames == ["Summary", "Cost Impact", "Exceptions", "Line Audit"]
    assert _summary(report["file"])["報告類型"] == REPORT_TYPE_COST + "（不含客戶報價風險）"
    assert any(f"報告類型：{REPORT_TYPE_COST}" in s.value for s in app.subheader)
    assert any("不含客戶報價風險" in c.value for c in app.caption)


def test_risk_mode_blocks_until_quotes_are_uploaded():
    app = _app()
    app.radio(key="report_mode").set_value(REPORT_TYPE_RISK).run()
    assert len(app.file_uploader) == 3
    _upload(app, "bom", "sample_bom.xlsx")
    _upload(app, "quote", "sample_price_increase.xlsx")
    assert RISK_BUTTON not in _labels(app)            # ③ missing: no report can be produced
    assert any("③" in w.value for w in app.warning)
    _upload(app, "open_quotes", "sample_open_quotes.xlsx")
    next(b for b in app.button if b.label == RISK_BUTTON).click().run()
    content = app.session_state["latest_report"]["file"]
    assert openpyxl.load_workbook(io.BytesIO(content)).sheetnames[-2:] == ["Quote Risk", "Quote Exceptions"]
    assert _summary(content)["報告類型"] == REPORT_TYPE_RISK + "（含成本影響）"
    assert any(f"報告類型：{REPORT_TYPE_RISK}" in s.value for s in app.subheader)


def test_risk_mode_with_unreadable_quotes_gives_no_report():
    app = _app()
    app.radio(key="report_mode").set_value(REPORT_TYPE_RISK).run()
    _upload(app, "bom", "sample_bom.xlsx")
    _upload(app, "quote", "sample_price_increase.xlsx")
    app.file_uploader(key="open_quotes").upload("wrong.xlsx", (S / "sample_bom.xlsx").read_bytes()).run()
    assert RISK_BUTTON not in _labels(app) and "latest_report" not in app.session_state
    assert any("無法讀取必要工作表" in e.value for e in app.error)


def test_switching_mode_invalidates_the_previous_report():
    app = _app()
    app.radio(key="report_mode").set_value(REPORT_TYPE_COST).run()
    _upload(app, "bom", "sample_bom.xlsx")
    _upload(app, "quote", "sample_price_increase.xlsx")
    next(b for b in app.button if b.label == COST_BUTTON).click().run()
    assert app.download_button
    app.radio(key="report_mode").set_value(REPORT_TYPE_RISK).run()
    _upload(app, "open_quotes", "sample_open_quotes.xlsx")
    assert not app.download_button                     # old cost-only report cannot be downloaded as risk report


def test_report_type_row_in_excel_is_formula_safe():
    from core.calculator import calculate_cost_impact
    from core.matcher import match_prices
    from core.reader import read_bom, read_price_increase
    from core.report import build_report
    matched = match_prices(read_bom(S / "sample_bom.xlsx").data, read_price_increase(S / "sample_price_increase.xlsx").data,
                           dt.date(2026, 12, 1))
    content = build_report(matched, calculate_cost_impact(matched, None), dt.date(2026, 12, 1))
    assert _summary(content)["報告類型"].startswith(REPORT_TYPE_COST)
    wb = openpyxl.load_workbook(io.BytesIO(content))
    assert not [c for ws in wb for row in ws.iter_rows() for c in row if c.data_type == "f"]
