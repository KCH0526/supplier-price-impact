"""Demo and sales material: example result must equal a fresh run; docs stay honest."""

import importlib.util
import io
import re
from pathlib import Path

import openpyxl

ROOT = Path(__file__).resolve().parents[1]
DEMO = ROOT / "demo"


def _builder():
    spec = importlib.util.spec_from_file_location("build_example_result", DEMO / "build_example_result.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _values(content):
    wb = openpyxl.load_workbook(io.BytesIO(content) if isinstance(content, bytes) else content, data_only=True)
    return {ws.title: [list(r) for r in ws.iter_rows(values_only=True)] for ws in wb}


def test_example_result_equals_a_fresh_run_of_the_three_samples():
    fresh = _values(_builder().build())
    committed = _values(DEMO / "example_result.xlsx")
    assert committed == fresh
    summary = dict((r[0], r[1]) for r in committed["Summary"])
    assert summary["預估每月總成本增加（TWD）"] == 61597
    assert summary["客戶報價：需人工覆核"] == 3
    assert summary["試算基準日"] == "2026-12-01"


def test_demo_inputs_are_the_synthetic_samples():
    module = _builder()
    for path in module.INPUTS.values():
        assert path.parent == ROOT / "samples"
        assert path.exists()


DOCS = ["DEMO_SCRIPT.md", "FIRST_TIME_GUIDE.md", "ONE_PAGER.md", "SERVICE_SCOPE.md"]


def test_demo_documents_exist_and_state_synthetic_data():
    for name in DOCS:
        text = (ROOT / "docs" / name).read_text(encoding="utf-8")
        assert "合成" in text, name


def test_no_unverified_commercial_claims():
    forbidden = ["已成交", "客戶見證", "官方認證", "已獲認證", "保證獲利", "市場唯一", "沒有競爭"]
    for name in DOCS + ["../README.md"]:
        text = (ROOT / "docs" / name).read_text(encoding="utf-8")
        for word in forbidden:
            for m in re.finditer(word, text):
                line = text[text.rfind("\n", 0, m.start()) + 1: text.find("\n", m.start())]
                assert any(neg in line for neg in ("不", "沒有", "未", "無")), f"{name}: {line}"


def test_referenced_images_exist():
    for name in DOCS + ["../README.md"]:
        text = (ROOT / "docs" / name).read_text(encoding="utf-8")
        for target in re.findall(r"!\[[^\]]*\]\(([^)]+)\)", text):
            assert ((ROOT / "docs" / name).parent / target).resolve().exists(), (name, target)


def test_readme_has_demo_entry():
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "docs/DEMO_SCRIPT.md" in text and "demo/example_result.xlsx" in text


def test_quote_recommendation_example_equals_a_fresh_run():
    spec = importlib.util.spec_from_file_location("qr", DEMO / "build_quote_recommendation_example.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    committed = _values(DEMO / "quote_recommendation_example.xlsx")
    assert committed == _values(module.build())
    rec = dict((r[0], r[1]) for r in committed["Quote Recommendation"][2:])
    assert rec["覆核狀態"] == "歷史價格低於安全底線" and rec["安全底價"] == 1026.12


def test_readme_covers_quote_memory_topics():
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    for topic in ("一句話", "系統主要優勢", "輔助分析，不取代 ERP", "歷史報價 Excel 的用途", "歷史報價匯入操作",
                  "相似案件查詢", "報價風險解讀", "Historical Evidence", "導入流程", "人工導入服務",
                  "商業化現況與未經驗證事項", "僅供內部試算，需人工核准", "沒有**使用 AI"):
        assert topic in text, topic
