"""PR #35: 案件工作台 page (storage off by default, explicit path, notices, reports, backup/restore)."""

import io
from pathlib import Path

import openpyxl
import pytest

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest

from core.case_store import CaseStore

ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "pages" / "4_案件工作台.py"
RFQ = (ROOT / "samples" / "rfq" / "rfq_sample.xlsx").read_bytes()
CASE = "C-001|RFQ-2612-001|v1"


def _page():
    app = AppTest.from_file(str(PAGE), default_timeout=30).run()
    assert not app.exception
    assert app.title[0].value == "案件工作台"
    return app


def _btn(app, label):
    return next(b for b in app.button if b.label == label)


def _texts(app):
    return " ".join(str(e.value) for kind in ("info", "warning", "success", "error", "markdown", "caption")
                    for e in getattr(app, kind))


def _enabled(tmp_path):
    app = _page()
    app.checkbox(key="store_enabled").check().run()
    app.text_input(key="db_path").set_value(str(tmp_path / "cases.db")).run()
    assert not app.exception
    return app


def _imported(tmp_path):
    app = _enabled(tmp_path)
    app.file_uploader(key="rfq_file").upload("rfq_sample.xlsx", RFQ).run()
    assert "尚未保存" in _texts(app)
    app.text_input(key="rfq_reason").set_value("客戶來信詢價").run()
    _btn(app, "保存詢價案件").click().run()
    assert not app.exception
    return app


def test_storage_is_off_by_default(tmp_path):
    app = _page()
    assert app.checkbox(key="store_enabled").value is False
    assert "資料保存未啟用" in _texts(app)
    assert not list(tmp_path.iterdir())


def test_path_must_be_explicit(tmp_path):
    app = _page()
    app.checkbox(key="store_enabled").check().run()
    assert "請輸入資料庫檔案路徑" in _texts(app)


def test_import_save_and_notice(tmp_path):
    app = _imported(tmp_path)
    assert "已保存" in _texts(app)
    store = CaseStore(tmp_path / "cases.db", enabled=True)
    assert len(store.list_cases()) == 4
    assert all(e["actor"] == "人工填寫（未經身分驗證）" for e in store.events(CASE))


def test_full_case_flow_and_separate_reports(tmp_path):
    app = _imported(tmp_path)
    app.selectbox(key="case_id").set_value(CASE).run()
    # status change: 待估價 -> 待人工覆核
    app.selectbox(key="new_status").set_value("待人工覆核").run()
    app.text_input(key="status_reason").set_value("成本已估算").run()
    _btn(app, "變更狀態").click().run()
    assert not app.exception
    # quote version
    app.selectbox(key="q_line").set_value("1").run()
    app.text_input(key="q_price").set_value("300").run()
    app.text_input(key="q_qty").set_value("100").run()
    app.text_input(key="q_unit_cost").set_value("200").run()
    app.text_input(key="q_reason").set_value("首次報價").run()
    _btn(app, "新增報價版本").click().run()
    assert not app.exception
    assert "報價未核准" in _texts(app)
    # outcome with total actual cost
    app.selectbox(key="o_line").set_value("1").run()
    app.radio(key="o_result").set_value("成交").run()
    app.text_input(key="o_won").set_value("100").run()
    app.text_input(key="o_actual_qty").set_value("100").run()
    app.radio(key="o_cost_mode").set_value("實際總成本").run()
    app.text_input(key="o_total").set_value("22500").run()
    app.text_input(key="o_reason").set_value("月結").run()
    _btn(app, "回填結果").click().run()
    assert not app.exception
    store = CaseStore(tmp_path / "cases.db", enabled=True)
    assert store.get_case(CASE)["status"] == "待人工覆核"
    assert store.outcomes(CASE, "1", 1)[0]["data"]["actual_total_cost"] == 22500
    labels = [d.label for d in app.download_button]
    assert "⬇️ 下載內部稽核報告（含成本，僅供內部）" in labels
    assert "⬇️ 下載客戶報價草稿（不含成本）" in labels
    # line 2 has no quote -> needs manual confirmation; line 1 analysis 25.00%
    text = _texts(app)
    assert "需人工確認" in text


def test_invalid_transition_is_not_offered(tmp_path):
    app = _imported(tmp_path)
    app.selectbox(key="case_id").set_value(CASE).run()
    assert "成交" not in app.selectbox(key="new_status").options


def test_incomplete_cost_notice(tmp_path):
    app = _imported(tmp_path)
    app.selectbox(key="case_id").set_value(CASE).run()
    app.selectbox(key="q_line").set_value("1").run()
    app.text_input(key="q_price").set_value("300").run()
    app.text_input(key="q_qty").set_value("100").run()
    app.text_input(key="q_unit_cost").set_value("200").run()
    app.text_input(key="q_reason").set_value("首次報價").run()
    _btn(app, "新增報價版本").click().run()
    app.selectbox(key="o_line").set_value("1").run()
    app.radio(key="o_result").set_value("成交").run()
    app.text_input(key="o_won").set_value("100").run()
    app.text_input(key="o_actual_qty").set_value("100").run()
    app.radio(key="o_cost_mode").set_value("明細成本").run()
    app.text_input(key="o_材料").set_value("15000").run()
    app.text_input(key="o_reason").set_value("部分月結").run()
    _btn(app, "回填結果").click().run()
    assert not app.exception
    assert "成本不完整" in _texts(app)


def test_reason_required(tmp_path):
    app = _enabled(tmp_path)
    app.file_uploader(key="rfq_file").upload("rfq_sample.xlsx", RFQ).run()
    _btn(app, "保存詢價案件").click().run()
    assert "原因" in " ".join(e.value for e in app.error)
    assert CaseStore(tmp_path / "cases.db", enabled=True).list_cases() == []


def test_backup_and_restore_requires_confirmation(tmp_path):
    app = _imported(tmp_path)
    dest = tmp_path / "bk" / "b1.db"
    app.text_input(key="backup_path").set_value(str(dest)).run()
    _btn(app, "建立備份").click().run()
    assert dest.exists()
    app.text_input(key="restore_path").set_value(str(dest)).run()
    _btn(app, "還原").click().run()
    assert any("確認" in e.value for e in app.error)
    app.checkbox(key="restore_confirm").check().run()
    _btn(app, "還原").click().run()
    assert not app.exception
    assert "已還原" in _texts(app)
