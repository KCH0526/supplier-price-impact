"""PR #25: 報價工作台 page and its internal report."""

import io
from decimal import Decimal
from pathlib import Path

import openpyxl
import pytest

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "pages" / "3_報價工作台.py"
MANUAL = {"單件材料變動成本": "100", "單件人工變動成本": "40", "單件製造費用": "30", "單件委外加工費": "10",
          "每批開機設定費": "1000", "每批換線治具費": "500", "其他批次固定費": "0"}


def _page():
    app = AppTest.from_file(str(PAGE), default_timeout=30).run()
    assert not app.exception
    assert app.title[0].value == "報價工作台"
    return app


def _btn(app, label):
    return next(b for b in app.button if b.label == label)


def _manual_tiers(app, margin=20.0, quantities="10, 100, 500"):
    app.radio(key="cost_mode").set_value("明細批次成本").run()
    app.radio(key="detail_source").set_value("手動輸入").run()
    app.text_input(key="m_product").set_value("P-DEMO").run()
    for k, v in MANUAL.items():
        app.text_input(key=f"m_{k}").set_value(v).run()
    app.text_input(key="m_source").set_value("合成示範").run()
    app.checkbox(key="m_confirmed").check().run()
    app.text_input(key="t_quantities").set_value(quantities).run()
    app.number_input(key="t_margin").set_value(margin).run()
    _btn(app, "計算數量階梯").click().run()
    assert not app.exception


def test_manual_cost_entry_gives_the_acceptance_tiers():
    app = _page()
    _manual_tiers(app)
    rows = {r["數量"]: r for r in app.session_state["tiers"]["result"].rows.to_dict("records")}
    assert (rows[10]["安全底價（試算）"], rows[100]["安全底價（試算）"], rows[500]["安全底價（試算）"]) == (
        Decimal("412.50"), Decimal("243.75"), Decimal("228.75"))
    labels = [d.label for d in app.download_button]
    assert any("內部覆核報告" in l for l in labels)


def test_blank_manual_cost_is_unknown_not_zero():
    app = _page()
    app.radio(key="cost_mode").set_value("明細批次成本").run()
    app.radio(key="detail_source").set_value("手動輸入").run()
    app.text_input(key="m_product").set_value("P-DEMO").run()
    assert app.text_input(key="m_單件人工變動成本").value == ""   # no default 0
    for k, v in MANUAL.items():
        if k != "單件人工變動成本":
            app.text_input(key=f"m_{k}").set_value(v).run()
    app.text_input(key="m_source").set_value("x").run()
    app.checkbox(key="m_confirmed").check().run()
    app.text_input(key="t_quantities").set_value("10").run()
    _btn(app, "計算數量階梯").click().run()
    rows = app.session_state["tiers"]["result"].rows.to_dict("records")
    assert rows[0]["安全底價（試算）"] is None and "空白" in rows[0]["說明"]


def test_changing_margin_invalidates_old_results():
    app = _page()
    _manual_tiers(app)
    assert any("內部覆核報告" in d.label for d in app.download_button)
    app.number_input(key="t_margin").set_value(25.0).run()
    assert not any("內部覆核報告" in d.label for d in app.download_button)


def test_internal_report_and_customer_draft_are_separate():
    app = _page()
    _manual_tiers(app)
    report = openpyxl.load_workbook(io.BytesIO(app.session_state["tiers"]["report"]))
    assert report.sheetnames == ["Summary", "Quantity Tiers", "Cost Basis"]
    assert "僅供內部試算" in str(report["Summary"]["A1"].value)
    # customer draft: prices are blank until typed
    app.text_input(key="d_customer").set_value("C-001").run()
    app.text_input(key="d_quote_no").set_value("SQ-DEMO-1").run()
    assert app.text_input(key="d_price_100").value == ""
    app.text_input(key="d_price_100").set_value("260").run()
    app.checkbox(key="d_confirmed").check().run()
    _btn(app, "產生客戶報價草稿").click().run()
    assert not app.exception
    draft = openpyxl.load_workbook(io.BytesIO(app.session_state["draft"]["file"]))
    assert draft.sheetnames == ["報價草稿"]
    text = " ".join(str(c.value) for ws in draft for row in ws.iter_rows() for c in row if c.value is not None)
    for secret in ("安全底價", "243.75", "412.50", "成本", "毛利", "1500", "合成示範"):
        assert secret not in text, secret
    assert "未核准草稿" in text  # 10 and 500 have no typed price
    assert "260" in text


def test_version_comparison_section():
    app = _page()
    std = (ROOT / "demo" / "historical_quotes_standardized_demo.xlsx").read_bytes()
    app.file_uploader(key="hist_std").upload("hist.xlsx", std).run()
    app.selectbox(key="v_quote").set_value("Q-2603-007").run()
    app.selectbox(key="v_a").set_value("1").run()
    app.selectbox(key="v_b").set_value("2").run()
    _btn(app, "比較兩個版本").click().run()
    assert not app.exception
    result = app.session_state["versions"]["result"]
    price = next(r for r in result.rows.to_dict("records") if r["欄位"] == "報價單價")
    assert price["差額"] == Decimal("-10")


def test_navigation_includes_workbench():
    assert 'title="報價工作台"' in (ROOT / "app.py").read_text(encoding="utf-8")
