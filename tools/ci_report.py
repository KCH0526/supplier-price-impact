"""Summarise a pytest JUnit XML report for CI and enforce 0 failed / 0 errors / 0 skipped.

Usage: python tools/ci_report.py pytest-junit.xml "<label>"
Writes a Markdown summary to $GITHUB_STEP_SUMMARY when it is set. Standard library only.
"""

from __future__ import annotations

import os
import platform
import sys
import xml.etree.ElementTree as ET


def counts(path: str) -> dict:
    root = ET.parse(path).getroot()
    suites = [root] if root.tag == "testsuite" else list(root.iter("testsuite"))
    total = {k: sum(int(s.get(k, 0)) for s in suites) for k in ("tests", "failures", "errors", "skipped")}
    total["passed"] = total["tests"] - total["failures"] - total["errors"] - total["skipped"]
    return total


def main(argv: list[str]) -> int:
    path, label = argv[1], argv[2] if len(argv) > 2 else platform.system()
    c = counts(path)
    line = (f"{label}: Python {platform.python_version()} ({platform.platform()}) - "
            f"passed {c['passed']}, failed {c['failures']}, errors {c['errors']}, skipped {c['skipped']}")
    print(line)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as fh:
            fh.write(f"### {label}\n\n{line}\n\n")
    ok = c["tests"] > 0 and c["failures"] == 0 and c["errors"] == 0 and c["skipped"] == 0
    if not ok:
        print("::error::Tests must be 0 failed, 0 errors, 0 skipped")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
