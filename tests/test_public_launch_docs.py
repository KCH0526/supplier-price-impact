"""Public launch decision and commercial documents must be complete and honest."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DECISION = ROOT / "docs" / "PUBLIC_LAUNCH_DECISION.md"
FORBIDDEN = ["已有使用者", "已獲得廣告收益", "保證核准", "保證收益", "已成交", "客戶見證", "官方認證"]


def _negated(text, word):
    for m in re.finditer(re.escape(word), text):
        line = text[text.rfind("\n", 0, m.start()) + 1: text.find("\n", m.start())]
        if not any(n in line for n in ("不", "沒有", "未", "無", "並非")):
            return line
    return None


def test_decision_covers_the_twelve_topics():
    text = DECISION.read_text(encoding="utf-8")
    for n, topic in enumerate(["目標客群", "詢價到報價流程", "功能對照", "模式比較", "前三個月", "系統界線",
                               "資料安全", "雲端資源成本", "AdSense", "不適合公開部署", "安全 SaaS", "Go／No-Go"], 1):
        assert re.search(rf"^## {n}\. .*{re.escape(topic)}", text, re.M), (n, topic)


def test_four_perspectives_with_objections_and_decisions():
    text = DECISION.read_text(encoding="utf-8")
    for role in ("報價主管", "SaaS 產品經理", "資安與資料保護工程師", "廣告與 B2B 商業化負責人"):
        assert role in text
    assert text.count("| 採納") + text.count("| **採納") >= 4
    assert "駁回" in text and "延期" in text


def test_no_unverified_claims():
    text = DECISION.read_text(encoding="utf-8")
    for word in FORBIDDEN:
        assert _negated(text, word) is None, word
    assert "不得公開接受真實企業資料" in text or "不公開接受真實企業資料" in text
