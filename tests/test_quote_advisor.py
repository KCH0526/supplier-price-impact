"""PR #18: recommendation and price warnings (spec section 6). Expected numbers are hand-derived literals."""

import datetime as dt
import io
import json
from decimal import Decimal
from pathlib import Path

import openpyxl
import pytest

from core.calculator import calculate_cost_impact
from core.historical_quotes import HIST_REQUIRED, HistoricalSource, import_historical_quotes
from core.matcher import match_prices
from core.quote_advisor import (
    INTERNAL_LABEL,
    STATUS_BELOW_FLOOR,
    STATUS_INSUFFICIENT,
    STATUS_NO_FLOOR,
    STATUS_REFERENCE,
    advise_quote,
)
from core.quote_search import search_similar_quotes
from core.reader import read_bom, read_price_increase, read_sheet

ROOT = Path(__file__).resolve().parents[1]
HIST = ROOT / "samples" / "historical"
SAMPLE_BOM = ROOT / "samples" / "sample_bom.xlsx"
SAMPLE_PRICE = ROOT / "samples" / "sample_price_increase.xlsx"
INCREASE = dt.date(2026, 12, 1)


def _costs(product_cost=True, bom=SAMPLE_BOM, price=SAMPLE_PRICE):
    pc = read_sheet(bom, "ProductCost", ["成品編號"]).data if product_cost else None
    return calculate_cost_impact(match_prices(read_bom(bom).data, read_price_increase(price).data, INCREASE), pc)


@pytest.fixture(scope="module")
def records():
    sources = []
    for name, file in (("sales_dept", "historical_quotes_sales_dept.xlsx"),
                       ("legacy_system", "historical_quotes_legacy_system.xlsx")):
        m = json.loads((HIST / f"mapping_{name}.json").read_text(encoding="utf-8"))["targets"]["HistoricalQuotes"]
        sources.append(HistoricalSource(file, (HIST / file).read_bytes(), m["source_sheet"], m["columns"]))
    return import_historical_quotes(sources).records


@pytest.fixture(scope="module")
def costs():
    return _costs()


def _advise(records, costs, as_of, margin="0.15", version="B", product="P-1001", qty=60, unit="pcs", **kw):
    search = search_similar_quotes(records, product, qty, as_of, unit, drawing_version=version)
    return advise_quote(search, records, costs, margin, price_increase_date=kw.pop("increase", INCREASE), **kw)


def _types(advice):
    return {w["類型"] for w in advice.warnings}


# ---------- A. cost safety floor ----------

def test_floor_p1001_15_percent(records, costs):
    a = _advise(records, costs, dt.date(2026, 12, 15))
    assert a.floor["可用"] is True
    assert a.floor["新完整成本"] == Decimal("872.20") and a.floor["原完整成本"] == Decimal("836.60")
    assert a.floor["安全底價"] == Decimal("1026.12")
    assert a.floor["目標毛利率"] == Decimal("0.15")


def test_floor_rounds_up_for_other_margins(records, costs):
    assert _advise(records, costs, dt.date(2026, 12, 15), margin="0.2").floor["安全底價"] == Decimal("1090.25")
    assert _advise(records, costs, dt.date(2026, 12, 15), margin="0.03").floor["安全底價"] == Decimal("899.18")
    a = _advise(records, costs, dt.date(2026, 12, 15), product="P-1002", qty=10, version=None)
    assert a.floor["安全底價"] == Decimal("346.12")  # 294.20 / 0.85 = 346.117...


def test_material_only_cost_gives_no_floor(records):
    a = _advise(records, _costs(product_cost=False), dt.date(2026, 12, 15))
    assert a.status == STATUS_NO_FLOOR
    assert a.floor["可用"] is False and a.floor["安全底價"] is None
    assert any("人工" in m for m in a.missing)
    assert "缺少目前完整成本" in _types(a)


def test_blocked_product_cost_gives_no_floor(records):
    edge = ROOT / "tests" / "fixtures"
    costs = _costs(product_cost=False, bom=edge / "test_bom_edge_cases.xlsx", price=edge / "test_price_edge_cases.xlsx")
    a = _advise(records, costs, dt.date(2026, 12, 15), product="P-X01", qty=1, version=None)
    assert a.status == STATUS_NO_FLOOR and a.floor["安全底價"] is None
    assert any("阻擋" in m or "不完整" in m for m in a.missing)


def test_unknown_product_gives_no_floor(records, costs):
    a = _advise(records, costs, dt.date(2026, 12, 15), product="P-0000", qty=1, version=None)
    assert a.status == STATUS_NO_FLOOR and any("不在" in m for m in a.missing)


def test_unit_other_than_pcs_gives_no_floor(records, costs):
    a = _advise(records, costs, dt.date(2026, 12, 15), unit="set", qty=20, version=None)
    assert a.floor["可用"] is False and any("pcs" in m for m in a.missing)


def test_invalid_margin_is_rejected(records, costs):
    for bad in ("1", "-0.1", "abc"):
        with pytest.raises(ValueError):
            _advise(records, costs, dt.date(2026, 12, 15), margin=bad)


# ---------- B + C. status ----------

def test_history_below_floor_status_and_warning(records, costs):
    a = _advise(records, costs, dt.date(2026, 12, 15))
    assert a.status == STATUS_BELOW_FLOOR
    assert a.reference["最低"] == Decimal("990") and a.reference["中位數"] == Decimal("1050")
    w = next(w for w in a.warnings if w["類型"] == "歷史價格低於安全底線")
    assert "990" in w["說明"] and "1026.12" in w["說明"] and "不得直接沿用舊價" in w["說明"]
    assert INTERNAL_LABEL == "僅供內部試算，需人工核准"
    assert len(a.evidence) == 3


def test_insufficient_history_still_shows_floor(records, costs):
    a = _advise(records, costs, dt.date(2026, 12, 1))
    assert a.status == STATUS_INSUFFICIENT
    assert a.floor["安全底價"] == Decimal("1026.12") and a.reference is None
    assert "歷史資料品質不足" in _types(a)


def test_reference_range_above_floor(records, costs):
    a = _advise(records, costs, dt.date(2026, 12, 1), margin="0.03", version=None)
    assert a.status == STATUS_REFERENCE
    assert a.floor["安全底價"] == Decimal("899.18") and a.reference["最低"] == Decimal("950")
    assert "歷史價格低於安全底線" not in _types(a)


# ---------- warnings ----------

def test_material_increase_but_same_old_price(records, costs):
    a = _advise(records, costs, dt.date(2026, 12, 15))
    w = next(w for w in a.warnings if w["類型"] == "材料漲價後仍沿用舊價")
    assert "Q-2612-002" in w["依據"] and "Q-2609-021" in w["依據"] and "1050" in w["說明"]


def test_no_material_warning_without_increase_date(records, costs):
    a = _advise(records, costs, dt.date(2026, 12, 15), increase=None)
    assert "材料漲價後仍沿用舊價" not in _types(a)


def test_other_units_are_flagged(records, costs):
    a = _advise(records, costs, dt.date(2026, 12, 15))
    w = next(w for w in a.warnings if w["類型"] == "價格單位不一致")
    assert "set" in w["說明"]


def test_old_drawing_reuse(records, costs):
    a = _advise(records, costs, dt.date(2026, 12, 15), version="C")
    w = next(w for w in a.warnings if w["類型"] == "舊版價格風險")
    assert "Q-2612-002" in w["依據"] and "B" in w["說明"]


def test_proposed_price_below_floor(records, costs):
    a = _advise(records, costs, dt.date(2026, 12, 15), proposed_price="1000")
    w = next(w for w in a.warnings if w["類型"] == "擬報價低於安全底線")
    assert "1000" in w["說明"] and "1026.12" in w["說明"]
    ok = _advise(records, costs, dt.date(2026, 12, 15), proposed_price="1026.12")
    assert "擬報價低於安全底線" not in _types(ok)


def test_price_spread_anomaly():
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "HistoricalQuotes"
    ws.append(HIST_REQUIRED)
    for i, price in enumerate((100, 100, 150)):
        ws.append([f"Q{i}", "1", dt.datetime(2026, 1, 1 + i), "C", "P-1001", 10, "pcs", "TWD", price, "未稅"])
    buf = io.BytesIO()
    wb.save(buf)
    recs = import_historical_quotes([HistoricalSource("s.xlsx", buf.getvalue(), "HistoricalQuotes")]).records
    a = advise_quote(search_similar_quotes(recs, "P-1001", 10, dt.date(2026, 6, 1), "pcs"), recs, _costs(), "0.15")
    w = next(w for w in a.warnings if w["類型"] == "同條件價格差異過大")
    assert "50.00%" in w["說明"]  # (150 - 100) / 100


def test_no_price_is_ever_zero_or_invented(records):
    a = _advise(records, _costs(product_cost=False), dt.date(2026, 12, 1))
    assert a.floor["安全底價"] is None and a.reference is None
    assert a.status == STATUS_NO_FLOOR
