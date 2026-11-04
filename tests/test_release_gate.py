"""PR #11 release-gate checks: malformed uploads, Docker build options, docs."""

import io
import re
import zipfile
from pathlib import Path

from core.quote_reader import read_open_quotes
from core.reader import read_bom
from core.validation import has_blocking

ROOT = Path(__file__).resolve().parents[1]
SAMPLE_BOM = ROOT / "samples" / "sample_bom.xlsx"


def _rewrite_member(path, member, new_bytes):
    src = zipfile.ZipFile(path)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as dst:
        for info in src.infolist():
            data = new_bytes if info.filename == member else src.read(info.filename)
            dst.writestr(info.filename, data)
    return buf.getvalue()


# ---------- malformed XLSX must become a blocking issue, never a crash ----------

def test_corrupted_sheet_xml_is_a_blocking_issue_not_an_exception():
    bad = _rewrite_member(SAMPLE_BOM, "xl/worksheets/sheet1.xml", b"<worksheet><sheetData><row><c")
    result = read_bom(bad)
    assert result.data is None and has_blocking(result.issues)
    assert "無法讀取" in result.issues[0].reason


def test_corrupted_cell_value_found_while_reading_rows_is_a_blocking_issue():
    # Well-formed XML, but a numeric cell holds text: openpyxl only fails while
    # iterating rows, after the workbook opened successfully.
    xml = zipfile.ZipFile(SAMPLE_BOM).read("xl/worksheets/sheet1.xml").decode()
    broken = xml.replace('<x:c r="F2" s="8" t="n"><x:v>2</x:v>', '<x:c r="F2" s="8" t="n"><x:v>abc</x:v>')
    assert broken != xml
    result = read_bom(_rewrite_member(SAMPLE_BOM, "xl/worksheets/sheet1.xml", broken.encode()))
    assert result.data is None and has_blocking(result.issues)
    assert result.issues[0].sheet == "BOM"
    assert "內容損毀" in result.issues[0].reason


def test_truncated_file_is_a_blocking_issue():
    data = SAMPLE_BOM.read_bytes()
    result = read_bom(data[: len(data) // 2])
    assert result.data is None and has_blocking(result.issues)


def test_empty_upload_is_a_blocking_issue():
    for reader in (read_bom, read_open_quotes):
        result = reader(b"")
        assert result.data is None and has_blocking(result.issues)


# ---------- Dockerfile: optional corporate CA without baking it into the image ----------

def test_dockerfile_supports_optional_corporate_ca_as_build_secret():
    text = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "--mount=type=secret,id=corp_ca" in text
    assert "required=false" in text
    # The certificate must never be copied into an image layer.
    assert "COPY" not in "\n".join(l for l in text.splitlines() if "ca" in l.lower() and "COPY" in l)


# ---------- documentation integrity ----------

def _markdown_files():
    return [ROOT / "README.md", *sorted((ROOT / "docs").glob("*.md"))]


def test_markdown_tables_are_not_broken_by_paragraphs():
    """Every table row must belong to a block that starts with header + separator."""
    problems = []
    for path in _markdown_files():
        lines = path.read_text(encoding="utf-8").splitlines()
        in_code = False
        for i, line in enumerate(lines):
            if line.startswith("```"):
                in_code = not in_code
            if in_code or not line.startswith("|"):
                continue
            prev = lines[i - 1] if i else ""
            if prev.startswith("|"):
                continue
            nxt = lines[i + 1] if i + 1 < len(lines) else ""
            if not re.match(r"^\|\s*:?-{3,}", nxt):
                problems.append(f"{path.name}:{i + 1}")
    assert problems == []


def test_work_log_has_no_stale_in_progress_markers():
    text = (ROOT / "docs" / "WORK_LOG.md").read_text(encoding="utf-8")
    assert "本 PR" not in text
    assert "622f3bb" in text  # PR #10 merge commit recorded


def test_release_gate_lists_the_four_evidence_levels():
    text = (ROOT / "docs" / "RELEASE_GATE.md").read_text(encoding="utf-8")
    for heading in ("已實際通過", "只有程式測試通過", "尚未驗證", "商業化前仍須確認"):
        assert heading in text


# ---------- blocking exceptions survive end to end ----------

def test_blocking_exceptions_flow_through_to_quotes_and_report():
    import datetime as dt
    from io import BytesIO

    import openpyxl
    import pandas as pd

    from core.calculator import calculate_cost_impact
    from core.matcher import match_prices
    from core.quote_reader import QUOTE_REQUIRED_COLUMNS
    from core.quote_risk import STATUS_UNRELIABLE, assess_quote_risk
    from core.reader import read_price_increase
    from core.report import build_report

    as_of = dt.date(2026, 12, 1)
    fixtures = ROOT / "tests" / "fixtures"
    matched = match_prices(read_bom(fixtures / "test_bom_edge_cases.xlsx").data,
                           read_price_increase(fixtures / "test_price_edge_cases.xlsx").data, as_of)
    product_cost = pd.DataFrame([{"成品編號": p, "單件人工成本": 10, "單件製造費用": 10, "單件其他成本": 0}
                                 for p in ("P-X01", "P-X02")])
    costs = calculate_cost_impact(matched, product_cost)
    d1, d2 = dt.datetime(2026, 11, 1), dt.datetime(2027, 1, 31)
    quotes = pd.DataFrame([["Q", str(i), p, "C", 9999, "TWD", 1, d1, d2, "有效"]
                           for i, p in enumerate(("P-X01", "P-X02"), 1)], columns=QUOTE_REQUIRED_COLUMNS, dtype=object)
    quotes.insert(0, "excel_row", [2, 3])
    risk = assess_quote_risk(quotes, costs, as_of)
    assert set(risk.risk["覆核狀態"]) == {STATUS_UNRELIABLE}
    assert risk.risk["新毛利率"].isna().all() and risk.risk["維持底線所需最低單價"].isna().all()

    wb = openpyxl.load_workbook(BytesIO(build_report(matched, costs, as_of, risk)), data_only=True)
    impact = [dict(zip([c.value for c in wb["Cost Impact"][1]], r))
              for r in wb["Cost Impact"].iter_rows(min_row=2, values_only=True)]
    assert all(r["原成本"] is None and r["新成本"] is None for r in impact)
    blocking = [r for r in wb["Exceptions"].iter_rows(min_row=2, values_only=True) if r[1] is True]
    assert len(blocking) >= 14
    assert dict(wb["Summary"].values)["預估每月總成本增加（TWD）"] is None
