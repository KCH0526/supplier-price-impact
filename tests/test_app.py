"""A real Streamlit widget-flow smoke test, including both uploaded XLSX files."""

from io import BytesIO
from pathlib import Path

import openpyxl
import pytest

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]


def test_full_sample_upload_can_download_an_auditable_report():
    app = AppTest.from_file(str(ROOT / "app.py"), default_timeout=20).run()
    assert not app.exception
    assert app.title[0].value == "供應商漲價影響試算器"
    app.file_uploader[0].upload("sample_bom.xlsx", (ROOT / "samples" / "sample_bom.xlsx").read_bytes())
    app.file_uploader[1].upload("sample_price_increase.xlsx", (
        ROOT / "samples" / "sample_price_increase.xlsx").read_bytes())
    app.run()
    assert not app.exception
    assert app.button[0].label == "產生報告"
    app.button[0].click().run()
    assert not app.exception
    assert len(app.download_button) == 1
    content = app.session_state["latest_report"]["file"]
    wb = openpyxl.load_workbook(BytesIO(content), data_only=True)
    assert wb.sheetnames == ["Summary", "Cost Impact", "Exceptions", "Line Audit"]
    assert wb["Cost Impact"].max_row == 7
    assert dict(wb["Summary"].values)["預估每月總成本增加（TWD）"] == 61597
    wb.close()
