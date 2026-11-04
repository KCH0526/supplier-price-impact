"""Public synthetic-data demo: static, pre-generated, no upload path, correct numbers."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEMO = ROOT / "web" / "demo"
PAGES = {
    "index.html": ["供應商漲價前後", "毛利風險", "歷史報價", "數量階梯", "報價版本差異", "客戶報價草稿"],
    "cost.html": ["836.60", "872.20", "35.60", "61,597.00"],
    "quote-risk.html": ["需人工覆核", "1,026.12", "SQ-2611-001", "12.78%"],
    "history.html": ["歷史價格低於安全底線", "1,026.12", "圖面版次不同", "選入", "排除"],
    "tiers.html": ["412.50", "243.75", "228.75", "未計入", "無條件進位"],
    "versions.html": ["Q-2603-007", "-10.00", "-1.00%", "依報價日期判斷先後"],
    "draft.html": ["報價草稿", "允許", "示範"],
}
NOTICE = "這是合成示範資料"


def test_demo_pages_exist_with_expected_numbers_and_notice():
    for name, needles in PAGES.items():
        text = (DEMO / name).read_text(encoding="utf-8")
        assert NOTICE in text, name
        for needle in needles:
            assert needle in text, (name, needle)


def test_demo_has_no_inputs_and_public_site_has_no_server_code():
    for path in DEMO.glob("*.html"):
        text = path.read_text(encoding="utf-8").lower()
        assert "<input" not in text and "<form" not in text and "<button" not in text, path.name
    web = ROOT / "web"
    assert not [p for p in web.rglob("*") if p.suffix in (".py", ".sh", ".toml", ".cfg") or p.name == "Dockerfile"]
    # Demo pages and all scripts / styles must not reference the private app or any upload code.
    # (install.html may tell enterprise users how to start the private app on their own computer.)
    for path in [*DEMO.glob("*.html"), *web.rglob("*.js"), *web.rglob("*.css")]:
        if path.is_file():
            text = path.read_text(encoding="utf-8").lower()
            for word in ("streamlit", ":8501", "_stcore", "file_uploader", "upload"):
                assert word not in text, (path.name, word)


def test_customer_draft_preview_contains_no_internal_data():
    text = (DEMO / "draft.html").read_text(encoding="utf-8")
    section = text[text.index("<!-- draft-start -->"): text.index("<!-- draft-end -->")]
    for secret in ("安全底價", "412.50", "243.75", "228.75", "成本", "毛利", "C-002", "合成示範：驗收案例"):
        assert secret not in section, secret


def test_demo_source_escapes_values():
    import importlib.util
    spec = importlib.util.spec_from_file_location("demo_content", ROOT / "web_src" / "demo_content.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.cell('<script>alert(1)</script>') == "&lt;script&gt;alert(1)&lt;/script&gt;"
