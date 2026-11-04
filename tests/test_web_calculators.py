"""Public website calculators (web/assets/calculators.js), run in Node.

Expected values are hand-derived literals. The same file runs in the browser.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / "web" / "assets" / "calculators.js"


def run(fn, *args):
    node = shutil.which("node")
    assert node, "Node.js is required to test the website calculators"
    script = (f"const c = require({json.dumps(str(JS))});"
              f"try {{ console.log(JSON.stringify({{ok: c.{fn}(...{json.dumps(list(args))})}})); }}"
              f"catch (e) {{ console.log(JSON.stringify({{error: e.message}})); }}")
    out = subprocess.run([node, "-e", script], capture_output=True, text=True, check=True).stdout
    return json.loads(out)


def ok(fn, *args):
    result = run(fn, *args)
    assert "ok" in result, result
    return result["ok"]


def err(fn, *args):
    result = run(fn, *args)
    assert "error" in result, result
    return result["error"]


# 1. cost increase
def test_cost_increase():
    assert ok("costIncrease", "836.60", "872.20") == {"difference": "35.60", "percent": "4.26"}
    assert ok("costIncrease", "3", "2") == {"difference": "-1.00", "percent": "-33.33"}
    assert ok("costIncrease", "0.1", "0.3") == {"difference": "0.20", "percent": "200.00"}   # no float drift


@pytest.mark.parametrize("old,new", [("0", "1"), ("-1", "2"), ("", "1"), ("abc", "1"), ("1", "x"), ("1e3", "2")])
def test_cost_increase_rejects_bad_input(old, new):
    assert err("costIncrease", old, new)


# 2. margin / markup
def test_margin_and_markup_from_cost_and_price():
    assert ok("marginMarkup", "872.20", "1000") == {"margin": "12.78", "markup": "14.65"}
    assert ok("marginMarkup", "100", "100") == {"margin": "0.00", "markup": "0.00"}
    assert ok("marginMarkup", "120", "100") == {"margin": "-20.00", "markup": "-16.67"}


def test_margin_markup_conversion():
    assert ok("marginToMarkup", "20") == "25.00"       # 0.2 / 0.8
    assert ok("marginToMarkup", "15") == "17.65"       # 0.15 / 0.85 = 0.176470...
    assert ok("markupToMargin", "25") == "20.00"
    assert ok("markupToMargin", "100") == "50.00"
    assert err("marginToMarkup", "100") and err("marginToMarkup", "-1") and err("markupToMargin", "-5")


# 3. batch fixed-cost allocation
def test_batch_allocation():
    assert ok("batchAllocation", "180", "1500", "10") == {"fixedPerPiece": "150.00", "costPerPiece": "330.00"}
    assert ok("batchAllocation", "180", "1500", "7") == {"fixedPerPiece": "214.29", "costPerPiece": "394.29"}
    assert ok("batchAllocation", "0", "0", "1") == {"fixedPerPiece": "0.00", "costPerPiece": "0.00"}
    for bad in (("180", "1500", "0"), ("180", "1500", "2.5"), ("-1", "1500", "10"), ("180", "", "10")):
        assert err("batchAllocation", *bad)


# 4. quantity tiers with minimum price rounded up
def test_quantity_tiers_acceptance_case():
    rows = ok("quantityTiers", "180", "1500", "20", "10, 100, 500")
    assert [(r["quantity"], r["costPerPiece"], r["floor"]) for r in rows] == [
        (10, "330.00", "412.50"), (100, "195.00", "243.75"), (500, "183.00", "228.75")]


def test_quantity_tiers_round_up_and_moq():
    rows = ok("quantityTiers", "180", "1500", "20", "7", "")
    assert rows[0]["floor"] == "492.86"                     # (180 + 1500/7) / 0.8 = 492.857...
    rows = ok("quantityTiers", "872.20", "0", "10", "1")    # 872.20 / 0.9 = 969.111... -> 969.12, not 969.11
    assert rows[0]["floor"] == "969.12"
    rows = ok("quantityTiers", "180", "1500", "20", "10, 50", "50")
    assert rows[0]["floor"] is None and rows[0]["status"] == "低於最低訂購量"
    assert rows[1]["floor"] == "262.50"


@pytest.mark.parametrize("args", [
    ("180", "1500", "100", "10"), ("180", "1500", "-1", "10"), ("180", "1500", "20", ""), ("180", "1500", "20", "10, 10"),
    ("180", "1500", "20", "0"), ("180", "1500", "20", "1.5"), ("180", "1500", "20", ",".join(["1"] * 21)),
])
def test_quantity_tiers_reject_bad_input(args):
    assert err("quantityTiers", *args)
