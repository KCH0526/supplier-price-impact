"""PR #33: RFQ import and case status workflow."""

import datetime as dt
import io
from decimal import Decimal
from pathlib import Path

import openpyxl
import pytest

from core.case_store import ACTOR, CaseStore, StoreError
from core.field_mapper import TARGETS
from core.rfq import (
    RFQ_REQUIRED,
    STATUSES,
    TERMINAL,
    read_rfq,
    save_rfq_cases,
    validate_transition,
)

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "samples" / "rfq" / "rfq_sample.xlsx"
D = dt.datetime(2026, 12, 1)


def book(rows, header=None):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "RFQ"
    ws.append(header or RFQ_REQUIRED)
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


ROW = ["Q1", "1", "C-1", D, "P-1", 10, "pcs", "TWD"]


def test_spec_fields_statuses_and_mapping_target():
    assert RFQ_REQUIRED == ["詢價單號", "詢價行號", "客戶代碼", "詢價日期", "成品編號", "詢價數量", "計價單位", "幣別"]
    assert TARGETS["RFQ"].required == RFQ_REQUIRED
    assert STATUSES == ["待確認資料", "待估價", "待人工覆核", "已產生報價草稿", "已報價", "成交", "未成交", "作廢"]
    assert TERMINAL == {"成交", "未成交", "作廢"}


def test_sample_import_versions_are_separate_cases_and_ids_keep_zeros():
    r = read_rfq(SAMPLE)
    assert [i for i in r.issues if i.blocking] == []
    ids = {c["case_id"]: (c, lines) for c, lines in r.cases}
    assert set(ids) == {"C-001|RFQ-2612-001|v1", "C-001|RFQ-2612-001|v2", "00125|000045|v1", "C-002|RFQ-2612-003|v1"}
    v1, v1_lines = ids["C-001|RFQ-2612-001|v1"]
    assert v1["status"] == "待估價" and [l["line_no"] for l in v1_lines] == ["1", "2"]
    assert ids["C-001|RFQ-2612-001|v2"][1][0]["quantity"] == Decimal("200")
    assert ids["00125|000045|v1"][1][0]["line_no"] == "01"
    assert ids["C-002|RFQ-2612-003|v1"][1][0]["required_date"] is None
    assert v1_lines[0]["source_row"] == 2 and v1["source_file"] == SAMPLE.name


def test_missing_identifier_is_not_guessed():
    r = read_rfq(book([["Q1", None, "C-1", D, "P-1", 10, "pcs", "TWD"]]))
    assert r.cases == [] and any(i.column == "詢價行號" and i.blocking for i in r.issues)


@pytest.mark.parametrize("change, column", [({3: "2026-13-01"}, "詢價日期"), ({5: 0}, "詢價數量"),
                                            ({5: "很多"}, "詢價數量"), ({6: None}, "計價單位"), ({7: None}, "幣別")])
def test_invalid_values_block_the_line(change, column):
    row = list(ROW)
    for i, v in change.items():
        row[i] = v
    r = read_rfq(book([row, ["Q1", "2", "C-1", D, "P-2", 5, "pcs", "TWD"]]))
    assert any(i.column == column and i.blocking for i in r.issues)
    (case, lines), = r.cases
    assert [l["line_no"] for l in lines] == ["2"] and case["status"] == "待確認資料"


def test_identical_duplicate_kept_once_conflict_blocked():
    same = read_rfq(book([ROW, list(ROW)]))
    assert len(same.cases[0][1]) == 1 and any("重複" in i.reason for i in same.issues)
    conflict = read_rfq(book([ROW, ["Q1", "1", "C-1", D, "P-1", 99, "pcs", "TWD"]]))
    assert conflict.cases == [] and any("衝突" in i.reason and i.blocking for i in conflict.issues)


def test_status_transitions():
    validate_transition("待估價", "待人工覆核")
    validate_transition("已報價", "成交")
    validate_transition("已報價", "待人工覆核")       # revise the quote
    for old, new in (("待估價", "成交"), ("成交", "待估價"), ("作廢", "待估價"), ("待估價", "未知狀態"), ("待估價", "待估價")):
        with pytest.raises(StoreError):
            validate_transition(old, new)


def test_save_to_store_and_status_change_uses_rules(tmp_path):
    store = CaseStore(tmp_path / "c.db", enabled=True)
    store.initialize()
    saved = save_rfq_cases(store, read_rfq(SAMPLE), reason="匯入合成 RFQ")
    assert saved == 4
    with pytest.raises(StoreError):
        store.update_case_status("C-001|RFQ-2612-001|v1", "成交", reason="x", validator=validate_transition)
    store.update_case_status("C-001|RFQ-2612-001|v1", "待人工覆核", reason="已估價", source="UI",
                             validator=validate_transition)
    ev = store.events("C-001|RFQ-2612-001|v1")[-1]
    assert (ev["old_value"], ev["new_value"], ev["actor"]) == ("待估價", "待人工覆核", ACTOR)
    with pytest.raises(StoreError):
        save_rfq_cases(store, read_rfq(SAMPLE), reason="再次匯入")    # never overwrites existing cases


def test_mapping_path_with_different_column_names():
    header = ["單號", "項次", "客戶", "日期", "品號", "數量", "單位", "幣", "版"]
    data = book([["Q9", "1", "C-9", D, "P-9", 3, "pcs", "TWD", "2"]], header=header)
    cols = {"詢價單號": "單號", "詢價行號": "項次", "客戶代碼": "客戶", "詢價日期": "日期", "成品編號": "品號",
            "詢價數量": "數量", "計價單位": "單位", "幣別": "幣", "詢價版本": "版"}
    r = read_rfq(data, columns=cols)
    assert [c["case_id"] for c, _ in r.cases] == ["C-9|Q9|v2"]
