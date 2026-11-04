"""Streamlit widget-flow tests for the field-mapping page."""

import datetime as dt
from decimal import Decimal
from pathlib import Path

import pytest

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest

from core.calculator import calculate_cost_impact
from core.field_mapper import mapping_from_json
from core.matcher import match_prices
from core.reader import read_bom, read_price_increase, read_sheet

ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "pages" / "1_Excel_欄位對應.py"
ERP = (ROOT / "samples" / "sample_erp_export.xlsx").read_bytes()
CONFIG = (ROOT / "samples" / "sample_field_mapping.json").read_bytes()
BUTTON = "產生標準化 Excel"


def _page():
    app = AppTest.from_file(str(PAGE), default_timeout=30).run()
    assert not app.exception
    assert app.title[0].value == "Excel 欄位對應"
    return app


def _button(app):
    return next(b for b in app.button if b.label == BUTTON)


def test_loaded_config_produces_standard_file_with_identical_results():
    app = _page()
    app.file_uploader(key="mapping_config").upload("map.json", CONFIG, "application/json").run()
    for target in ("BOM", "ProductCost", "PriceIncrease", "OpenQuotes"):
        app.file_uploader(key=f"src_{target}").upload("erp.xlsx", ERP).run()
    assert not app.exception
    _button(app).click().run()
    assert not app.exception
    content = app.session_state["standard_file"]
    matched = match_prices(read_bom(content).data, read_price_increase(content).data, dt.date(2026, 12, 1))
    costs = calculate_cost_impact(matched, read_sheet(content, "ProductCost", ["成品編號"]).data)
    assert costs.summary["預估每月總成本增加"] == Decimal("61597.00")
    labels = [d.label for d in app.download_button]
    assert any("標準化 Excel" in l for l in labels) and any("對應設定" in l for l in labels)
    saved = mapping_from_json(app.session_state["mapping_json"])
    assert saved == mapping_from_json(CONFIG)


def test_without_config_nothing_is_guessed_and_required_fields_block():
    app = _page()
    app.file_uploader(key="src_BOM").upload("erp.xlsx", ERP).run()
    app.selectbox(key="sheet_BOM").set_value("產品結構明細").run()
    # Every mapping starts as "not mapped": no automatic guessing.
    assert app.selectbox(key="map_BOM_成品編號_0").value == "（不對應）"
    _button(app).click().run()
    assert not app.exception
    assert "standard_file" not in app.session_state
    assert any("必要欄位" in e.value for e in app.error)


def test_manual_duplicate_source_column_is_blocked():
    app = _page()
    app.file_uploader(key="src_BOM").upload("erp.xlsx", ERP).run()
    app.selectbox(key="sheet_BOM").set_value("產品結構明細").run()
    app.selectbox(key="map_BOM_成品名稱_0").set_value("主件品名").run()
    app.selectbox(key="map_BOM_子件名稱_0").set_value("主件品名").run()
    _button(app).click().run()
    assert any("重複對應" in e.value for e in app.error)


def test_invalid_config_file_shows_error():
    app = _page()
    app.file_uploader(key="mapping_config").upload("bad.json", b"{not json", "application/json").run()
    assert not app.exception
    assert any("對應設定" in e.value for e in app.error)


def test_changing_a_mapping_hides_the_old_standard_file():
    app = _page()
    app.file_uploader(key="mapping_config").upload("map.json", CONFIG, "application/json").run()
    for target in ("BOM", "PriceIncrease"):
        app.file_uploader(key=f"src_{target}").upload("erp.xlsx", ERP).run()
    _button(app).click().run()
    assert "standard_file" in app.session_state
    key = next(s.key for s in app.selectbox if s.key and s.key.startswith("map_BOM_原單價_"))
    app.selectbox(key=key).set_value("（不對應）").run()
    assert "standard_file" not in app.session_state
    assert not any("標準化 Excel" in d.label for d in app.download_button)


def test_standard_file_works_in_all_three_slots_of_the_main_page():
    app = _page()
    app.file_uploader(key="mapping_config").upload("map.json", CONFIG, "application/json").run()
    for target in ("BOM", "ProductCost", "PriceIncrease", "OpenQuotes"):
        app.file_uploader(key=f"src_{target}").upload("erp.xlsx", ERP).run()
    _button(app).click().run()
    content = app.session_state["standard_file"]
    main = AppTest.from_file(str(ROOT / "app.py"), default_timeout=30).run()
    for i in range(3):
        main.file_uploader[i].upload("standardized.xlsx", content)
    main.run()
    next(b for b in main.button if b.label == "產生毛利風險報告").click().run()
    assert not main.exception
    report = main.session_state["latest_report"]
    assert report["summary"]["預估每月總成本增加"] == Decimal("61597.00")
    assert report["risk"].summary["需人工覆核"] == 3


def test_main_app_navigation_uses_readable_page_titles():
    source = (ROOT / "app.py").read_text(encoding="utf-8")
    assert 'title="毛利風險報告"' in source and 'title="Excel 欄位對應"' in source


def test_preview_shows_excel_row_label_not_internal_name():
    app = _page()
    app.file_uploader(key="src_BOM").upload("erp.xlsx", ERP).run()
    app.selectbox(key="sheet_BOM").set_value("產品結構明細").run()
    preview = app.dataframe[0].value
    assert "Excel列號" in preview.columns and "excel_row" not in preview.columns
