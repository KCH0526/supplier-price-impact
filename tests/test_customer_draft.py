"""PR #21: customer quote draft built from an allow-list (spec section 2)."""

import datetime as dt
import inspect
import io
from decimal import Decimal

import openpyxl
import pytest

from core.customer_draft import (
    ALLOWED_HEADER,
    ALLOWED_LINE,
    LABEL_CONFIRMED,
    LABEL_UNAPPROVED,
    build_customer_draft,
    build_customer_draft_workbook,
)

HEADER = {"客戶代碼": "C-001", "客戶名稱": "北辰自動化（虛構）", "報價單號": "SQ-2612-010", "報價版本": "1",
          "報價日期": dt.date(2026, 12, 15), "報價有效期限": dt.date(2027, 1, 15), "交易條件": "月結 30 天"}
LINE = {"成品編號": "P-1001", "成品名稱": "鋁合金控制箱", "規格圖面版次": "B", "數量": 60, "計價單位": "pcs",
        "幣別": "TWD", "報價單價": "1050", "交期": "20 天"}
SECRETS = ["SECRET-B", "C-002", "872.20", "1026.12", "毛利", "安全底價", "成本", "990", "Q-2609-021", "內部備註",
           "風險", "供應商"]


def _cells(content):
    wb = openpyxl.load_workbook(io.BytesIO(content))
    return wb, [c for ws in wb for row in ws.iter_rows() for c in row]


def test_allow_lists_match_spec():
    assert ALLOWED_HEADER == ["客戶代碼", "客戶名稱", "報價單號", "報價版本", "報價日期", "報價有效期限", "交易條件"]
    assert ALLOWED_LINE == ["成品編號", "成品名稱", "規格圖面版次", "數量", "計價單位", "幣別", "報價單價", "交期"]


def test_internal_fields_passed_in_are_never_copied():
    header = dict(HEADER, 內部備註="SECRET-B 曾報 990", 其他客戶="C-002")
    line = dict(LINE, 安全底價=Decimal("1026.12"), 新完整成本="872.20", 毛利率="0.15", 歷史證據="Q-2609-021",
                供應商成本="供應商 V-001", 風險="高")
    content = build_customer_draft_workbook(build_customer_draft(header, [line], prices_confirmed=True))
    _, cells = _cells(content)
    text = " ".join(str(c.value) for c in cells if c.value is not None)
    for secret in SECRETS:
        assert secret not in text, secret
    assert "C-001" in text and "1050" in text


def test_builder_cannot_receive_internal_advice_objects():
    params = set(inspect.signature(build_customer_draft).parameters)
    assert params == {"header", "lines", "prices_confirmed"}


def test_single_visible_sheet_no_hidden_sheets_no_defined_names_no_formulas():
    line = dict(LINE, 成品名稱='=HYPERLINK("http://example.invalid","x")', 交期="@SUM(A1)")
    wb, cells = _cells(build_customer_draft_workbook(build_customer_draft(HEADER, [line], prices_confirmed=True)))
    assert wb.sheetnames == ["報價草稿"]
    assert all(ws.sheet_state == "visible" for ws in wb)
    assert len(wb.defined_names) == 0
    assert not [c for c in cells if c.data_type == "f"]


def test_blank_price_is_unapproved_never_zero():
    draft = build_customer_draft(HEADER, [dict(LINE, 報價單價=None)], prices_confirmed=True)
    assert draft.label == LABEL_UNAPPROVED
    assert draft.lines[0]["報價單價"] is None and draft.lines[0]["合計金額"] is None
    _, cells = _cells(build_customer_draft_workbook(draft))
    assert str(cells[0].value).startswith(LABEL_UNAPPROVED)
    assert not [c for c in cells if c.value == 0]


def test_unconfirmed_prices_are_unapproved_draft():
    assert build_customer_draft(HEADER, [LINE], prices_confirmed=False).label == LABEL_UNAPPROVED
    assert build_customer_draft(HEADER, [LINE], prices_confirmed=True).label == LABEL_CONFIRMED
    assert "不提供核准或簽名" in LABEL_CONFIRMED


@pytest.mark.parametrize("price", ["0", "-5", "待議", "nan"])
def test_invalid_price_is_rejected(price):
    with pytest.raises(ValueError):
        build_customer_draft(HEADER, [dict(LINE, 報價單價=price)], prices_confirmed=True)


@pytest.mark.parametrize("qty", [0, -1, "很多", None])
def test_invalid_quantity_is_rejected(qty):
    with pytest.raises(ValueError):
        build_customer_draft(HEADER, [dict(LINE, 數量=qty)], prices_confirmed=True)


def test_amount_precision():
    lines = [dict(LINE, 數量=3, 報價單價="0.335"), dict(LINE, 成品編號="P-1002", 數量=7, 報價單價="1026.12")]
    draft = build_customer_draft(HEADER, lines, prices_confirmed=True)
    assert draft.lines[0]["合計金額"] == Decimal("1.01")       # 1.005 -> 1.01 (half up)
    assert draft.lines[1]["合計金額"] == Decimal("7182.84")
    assert draft.total == Decimal("7183.85")


def test_one_customer_and_one_currency_per_draft():
    with pytest.raises(ValueError):
        build_customer_draft(dict(HEADER, 客戶代碼=None), [LINE], prices_confirmed=True)
    with pytest.raises(ValueError):
        build_customer_draft(HEADER, [LINE, dict(LINE, 幣別="USD")], prices_confirmed=True)
    with pytest.raises(ValueError):
        build_customer_draft(HEADER, [], prices_confirmed=True)


def test_label_is_first_row_and_no_signature_text():
    wb, cells = _cells(build_customer_draft_workbook(build_customer_draft(HEADER, [LINE], prices_confirmed=True)))
    ws = wb["報價草稿"]
    assert ws["A1"].value == LABEL_CONFIRMED
    text = " ".join(str(c.value) for c in cells if c.value)
    assert "核准人" not in text and "已核准" not in text


def test_internal_report_is_unchanged():
    # The existing internal quote-memory report still carries its internal label.
    from core.quote_memory_report import SHEETS
    assert SHEETS == ["Summary", "Quote Recommendation", "Historical Evidence", "Price Exceptions", "Data Quality"]
