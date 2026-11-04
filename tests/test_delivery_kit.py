"""PR #15 customer delivery kit: complete, honest, legal texts marked as drafts."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KIT = ROOT / "docs" / "delivery"

FILES = {
    "README.md": "交付工具包",
    "01_ONBOARDING_FLOW.md": "第一次導入流程",
    "02_DATA_REQUEST.md": "資料需求表",
    "03_DEIDENTIFICATION_AND_CONSENT.md": "去識別化",
    "04_FIELD_MAPPING_SIGNOFF.md": "欄位對應確認表",
    "05_COST_BASIS_CONFIRMATION.md": "成本口徑確認表",
    "06_RESULT_ACCEPTANCE.md": "結果人工驗收表",
    "07_SERVICE_PACKAGE.md": "服務範圍",
    "08_CLIENT_FAQ.md": "常見客戶問題",
    "09_DATA_DELETION.md": "資料清除",
    "11_TRIAL_KIT.md": "第一位客戶試用",
}
LEGAL = ["03_DEIDENTIFICATION_AND_CONSENT.md", "07_SERVICE_PACKAGE.md", "09_DATA_DELETION.md", "11_TRIAL_KIT.md"]


def _text(name):
    return (KIT / name).read_text(encoding="utf-8")


def test_all_ten_deliverables_exist_with_their_topic():
    for name, topic in FILES.items():
        assert topic in _text(name), name


def test_index_links_every_document():
    index = _text("README.md")
    for name in FILES:
        if name != "README.md":
            assert f"({name})" in index, name


def test_legal_documents_are_marked_as_drafts_for_professional_review():
    for name in LEGAL:
        text = _text(name)
        assert "草案" in text and "專業" in text and "審閱" in text, name


def test_price_is_an_unverified_assumption():
    text = _text("07_SERVICE_PACKAGE.md")
    assert "NT$3,000～8,000" in text
    line = next(l for l in text.splitlines() if "NT$3,000～8,000" in l)
    assert "待" in line and "驗證" in line
    for word in ("已成交", "已證明", "市場價"):
        for m in re.finditer(word, text):
            ctx = text[text.rfind("\n", 0, m.start()) + 1: text.find("\n", m.start())]
            assert any(n in ctx for n in ("不", "未", "沒有", "並非")), ctx


def test_forms_have_signature_fields():
    for name in ("04_FIELD_MAPPING_SIGNOFF.md", "05_COST_BASIS_CONFIRMATION.md", "06_RESULT_ACCEPTANCE.md",
                 "09_DATA_DELETION.md"):
        assert "簽核" in _text(name) or "簽名" in _text(name), name


def test_markdown_tables_in_kit_are_well_formed():
    for path in KIT.glob("*.md"):
        lines = path.read_text(encoding="utf-8").splitlines()
        for i, line in enumerate(lines):
            if line.startswith("|") and not (i and lines[i - 1].startswith("|")):
                assert i + 1 < len(lines) and re.match(r"^\|\s*:?-{3,}", lines[i + 1]), f"{path.name}:{i + 1}"


def test_readme_links_the_kit():
    assert "docs/delivery/README.md" in (ROOT / "README.md").read_text(encoding="utf-8")


def test_trial_kit_prices_are_assumptions_and_no_customers_claimed():
    text = _text("11_TRIAL_KIT.md")
    for line in text.splitlines():
        if "NT$" in line:
            assert "假設" in line, line
    assert "沒有**任何付費客戶" in text
    assert text.count("?") + text.count("？") >= 10  # ten interview questions
