"""PR #38: tools/ci_report.py enforces 0 failed / 0 errors / 0 skipped in every CI job."""

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("ci_report", ROOT / "tools" / "ci_report.py")
ci_report = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ci_report)


def _xml(tmp_path, tests, failures=0, errors=0, skipped=0):
    p = tmp_path / "j.xml"
    p.write_text(f'<testsuites><testsuite name="pytest" tests="{tests}" failures="{failures}" errors="{errors}" '
                 f'skipped="{skipped}"/></testsuites>', encoding="utf-8")
    return str(p)


def test_all_passed(tmp_path, monkeypatch):
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    assert ci_report.counts(_xml(tmp_path, 561)) == {"tests": 561, "failures": 0, "errors": 0, "skipped": 0,
                                                     "passed": 561}
    assert ci_report.main(["x", _xml(tmp_path, 561), "Linux"]) == 0


@pytest.mark.parametrize("kw", [{"failures": 1}, {"errors": 1}, {"skipped": 1}])
def test_any_failure_error_or_skip_fails(tmp_path, monkeypatch, kw):
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    assert ci_report.main(["x", _xml(tmp_path, 561, **kw), "Linux"]) == 1


def test_no_tests_fails(tmp_path, monkeypatch):
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    assert ci_report.main(["x", _xml(tmp_path, 0), "Linux"]) == 1


def test_summary_is_written(tmp_path, monkeypatch):
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    ci_report.main(["x", _xml(tmp_path, 3), "Windows"])
    assert "Windows" in summary.read_text(encoding="utf-8") and "passed 3" in summary.read_text(encoding="utf-8")
