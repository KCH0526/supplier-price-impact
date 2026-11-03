"""Security and deployment acceptance checks (PR #6)."""

import datetime as dt
import io
import tomllib
import zipfile
from pathlib import Path

import openpyxl

import core.reader as reader
from core.calculator import calculate_cost_impact
from core.matcher import match_prices
from core.reader import read_bom, read_price_increase
from core.report import build_report
from core.validation import BOM_REQUIRED_COLUMNS, PRICE_REQUIRED_COLUMNS, has_blocking

ROOT = Path(__file__).resolve().parents[1]
SAMPLE_BOM = ROOT / "samples" / "sample_bom.xlsx"
AS_OF = dt.date(2026, 12, 1)


def _xlsx(sheet, header, rows, text_cells=()):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = sheet
    ws.append(header)
    for row in rows:
        ws.append(row)
    for coord, value in text_cells:  # Text cells beginning with "=" (Excel: '=...)
        ws[coord].value = value
        ws[coord].data_type = "s"
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ---------- Excel formula injection ----------

def test_report_never_contains_formulas_from_untrusted_text():
    payload = '=HYPERLINK("http://example.invalid","x")'
    bom = _xlsx("BOM", BOM_REQUIRED_COLUMNS, [["X", "n", "M-1", "x", "pcs", 1, 10]],
                text_cells=[("A2", payload), ("B2", "+1+1"), ("D2", "@SUM(1)")])
    price = _xlsx("PriceIncrease", PRICE_REQUIRED_COLUMNS,
                  [["M-1", "-cmd", "pcs", "TWD", 12, dt.datetime(2026, 12, 1)]])
    b, p = read_bom(bom).data, read_price_increase(price).data
    assert b.iloc[0]["成品編號"] == payload
    matched = match_prices(b, p, AS_OF)
    costs = calculate_cost_impact(matched, None)
    assert costs.summary["最高單件成本增加成品"] == payload  # reaches the Summary sheet
    wb = openpyxl.load_workbook(io.BytesIO(build_report(matched, costs, AS_OF)))
    formulas = [(ws.title, c.coordinate) for ws in wb for row in ws.iter_rows() for c in row
                if c.data_type == "f"]
    assert formulas == []
    summary = dict((r[0].value, r[1].value) for r in wb["Summary"].iter_rows())
    assert summary["最高單件成本增加成品"] == "'" + payload


def test_formula_cells_in_uploads_are_not_evaluated_or_trusted():
    # A real formula cell has no cached value when written by a script; the
    # reader uses data_only=True, so it becomes blank and is blocked.
    bom = _xlsx("BOM", BOM_REQUIRED_COLUMNS, [["=1+1", "n", "M-1", "x", "pcs", 1, 10]])
    data = read_bom(bom).data
    assert data.iloc[0]["成品編號"] is None


# ---------- archive / size limits ----------

def test_oversized_file_is_rejected(monkeypatch):
    monkeypatch.setattr(reader, "MAX_FILE_BYTES", 1000)
    result = read_bom(SAMPLE_BOM)
    assert result.data is None and has_blocking(result.issues)
    assert "檔案過大" in result.issues[0].reason


def test_decompression_bomb_is_rejected_before_parsing(monkeypatch):
    monkeypatch.setattr(reader, "MAX_UNCOMPRESSED_BYTES", 10_000)
    result = read_bom(SAMPLE_BOM.read_bytes())
    assert result.data is None and has_blocking(result.issues)
    assert "解壓縮後" in result.issues[0].reason


def test_high_compression_ratio_member_is_rejected():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", "<Types/>")
        zf.writestr("xl/worksheets/sheet1.xml", " " * 5_000_000)
    result = read_bom(buf.getvalue())
    assert result.data is None and has_blocking(result.issues)
    assert "壓縮比" in result.issues[0].reason


def test_too_many_rows_is_rejected(monkeypatch):
    monkeypatch.setattr(reader, "MAX_DATA_ROWS", 10)
    result = read_bom(SAMPLE_BOM)
    assert result.data is None and has_blocking(result.issues)
    assert "資料列過多" in result.issues[0].reason


def test_file_object_is_supported_after_guard():
    with open(SAMPLE_BOM, "rb") as fh:
        assert len(read_bom(fh).data) == 40


# ---------- deployment configuration ----------

def test_streamlit_config_disables_telemetry_and_limits_uploads():
    cfg = tomllib.loads((ROOT / ".streamlit" / "config.toml").read_text(encoding="utf-8"))
    assert cfg["browser"]["gatherUsageStats"] is False
    assert cfg["server"]["maxUploadSize"] <= 20  # MB; Streamlit default is 200
    assert cfg["server"]["headless"] is True
    # With headless + a wildcard bind address (Docker uses 0.0.0.0), Streamlit
    # calls checkip.amazonaws.com at startup unless browser.serverAddress is
    # set manually. Keep that outbound lookup disabled.
    assert cfg["browser"]["serverAddress"] == "localhost"
    # Hide the "Deploy" button that points users to public Streamlit hosting.
    assert cfg["client"]["toolbarMode"] == "minimal"


def test_docker_publishes_only_on_localhost_and_uses_python_311():
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    assert '"127.0.0.1:8501:8501"' in compose
    assert "STREAMLIT_BROWSER_GATHER_USAGE_STATS" in compose
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert dockerfile.startswith("FROM python:3.11")
    assert "USER " in dockerfile  # do not run the web server as root


def test_secrets_and_outputs_are_ignored():
    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    dockerignore = (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
    for pattern in (".env", ".streamlit/secrets.toml", "result.xlsx"):
        assert pattern in gitignore
        assert pattern in dockerignore
