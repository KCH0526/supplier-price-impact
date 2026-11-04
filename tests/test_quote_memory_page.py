"""PR #19: Streamlit page 「歷史報價與建議報價」."""

import io
from pathlib import Path

import openpyxl
import pytest

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "pages" / "2_歷史報價與建議報價.py"
HIST = ROOT / "samples" / "historical"


def _page():
    app = AppTest.from_file(str(PAGE), default_timeout=30).run()
    assert not app.exception
    assert app.title[0].value == "歷史報價與建議報價"
    return app


def _button(app, label):
    return next(b for b in app.button if b.label == label)


def _import(app):
    hist = app.file_uploader(key="hist_files")
    hist.upload("historical_quotes_sales_dept.xlsx", (HIST / "historical_quotes_sales_dept.xlsx").read_bytes())
    hist.upload("historical_quotes_legacy_system.xlsx", (HIST / "historical_quotes_legacy_system.xlsx").read_bytes())
    maps = app.file_uploader(key="hist_mappings")
    maps.upload("mapping_sales_dept.json", (HIST / "mapping_sales_dept.json").read_bytes(), "application/json")
    maps.upload("mapping_legacy_system.json", (HIST / "mapping_legacy_system.json").read_bytes(), "application/json")
    app.run()
    app.selectbox(key="hist_map_0").set_value("mapping_sales_dept.json").run()
    app.selectbox(key="hist_map_1").set_value("mapping_legacy_system.json").run()
    _button(app, "匯入歷史報價").click().run()
    assert not app.exception


def _costs(app):
    app.file_uploader(key="cost_bom").upload("sample_bom.xlsx", (ROOT / "samples" / "sample_bom.xlsx").read_bytes())
    app.file_uploader(key="cost_price").upload("sample_price_increase.xlsx",
                                              (ROOT / "samples" / "sample_price_increase.xlsx").read_bytes())
    app.run()


def test_import_shows_quality_and_standardized_download():
    app = _page()
    _import(app)
    imp = app.session_state["hist_import"]
    assert len(imp.records) == 15 and imp.summary["重複略過筆數"] == 1
    assert any("標準化歷史報價" in d.label for d in app.download_button)


def test_full_recommendation_flow_and_report():
    app = _page()
    _import(app)
    _costs(app)
    app.selectbox(key="q_product").set_value("P-1001").run()
    app.number_input(key="q_qty").set_value(60).run()
    app.text_input(key="q_version").set_value("B").run()
    app.date_input(key="q_as_of").set_value(__import__("datetime").date(2026, 12, 15)).run()
    app.checkbox(key="q_use_increase").check().run()
    _button(app, "產生建議報價").click().run()
    assert not app.exception
    advice = app.session_state["advice_result"]["advice"]
    assert advice.status == "歷史價格低於安全底線"
    assert str(advice.floor["安全底價"]) == "1026.12"
    texts = " ".join(str(e.value) for e in app.markdown) + " ".join(str(e.value) for e in app.caption)
    assert "僅供內部試算，需人工核准" in texts
    wb = openpyxl.load_workbook(io.BytesIO(app.session_state["advice_result"]["report"]))
    assert wb.sheetnames[0] == "Summary"


def test_without_cost_files_no_floor_is_shown():
    app = _page()
    _import(app)
    app.selectbox(key="q_product").set_value("P-1001").run()
    app.number_input(key="q_qty").set_value(60).run()
    _button(app, "產生建議報價").click().run()
    assert not app.exception
    assert app.session_state["advice_result"]["advice"].status == "無法提供安全底價"


def test_navigation_lists_the_new_page():
    assert 'title="歷史報價與建議報價"' in (ROOT / "app.py").read_text(encoding="utf-8")
