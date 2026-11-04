"""PR #31: commercialization and launch-readiness documents."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
L = ROOT / "docs" / "launch"
FILES = {
    "README.md": "上線準備文件",
    "PUBLIC_SITE_GUIDE.md": "公開網站操作說明",
    "ENTERPRISE_DEPLOYMENT.md": "企業私有版部署說明",
    "FREE_VS_ENTERPRISE.md": "免費與企業版功能比較",
    "DEAL_TRACKER.md": "成交／未成交假設追蹤表",
    "PRIVACY_POLICY_DRAFT.md": "隱私權政策",
    "TERMS_OF_SERVICE_DRAFT.md": "服務條款",
    "DATA_RETENTION_POLICY_DRAFT.md": "資料保存與刪除政策",
    "ADS_REVIEW_CHECKLIST.md": "廣告導入審查清單",
    "SEO_CHECKLIST.md": "SEO 驗收清單",
    "COST_TRAFFIC_ESTIMATE.md": "成本與流量預估表",
    "PRELAUNCH_SECURITY_CHECK.md": "上線前安全檢查",
    "USER_DECISIONS.md": "使用者決策清單",
}
DRAFTS = ["PRIVACY_POLICY_DRAFT.md", "TERMS_OF_SERVICE_DRAFT.md", "DATA_RETENTION_POLICY_DRAFT.md"]


def text(name):
    return (L / name).read_text(encoding="utf-8")


def test_all_documents_exist_and_are_indexed():
    for name, topic in FILES.items():
        assert topic in text(name), name
    index = text("README.md")
    for name in FILES:
        if name != "README.md":
            assert f"({name})" in index, name
    for ref in ("../delivery/01_ONBOARDING_FLOW.md", "../delivery/11_TRIAL_KIT.md"):
        assert ref in index and (L / ref).resolve().exists()


def test_legal_documents_are_drafts_for_professional_review():
    for name in DRAFTS:
        t = text(name)
        assert "草案" in t and "專業" in t and "審閱" in t, name


def test_no_ad_account_ids_or_tracking_codes_anywhere():
    for path in [*L.glob("*.md"), *(ROOT / "web").rglob("*.html")]:
        t = path.read_text(encoding="utf-8")
        assert not re.search(r"ca-pub-\d+", t), path.name
        assert "adsbygoogle.js" not in t and "googletagmanager.com/gtag" not in t, path.name


def test_no_claims_of_users_revenue_or_approval():
    for name in FILES:
        t = text(name)
        for word in ("已有付費客戶", "已獲得收益", "保證核准", "保證收益", "已成交", "已部署"):
            for m in re.finditer(word, t):
                line = t[t.rfind("\n", 0, m.start()) + 1: t.find("\n", m.start())]
                assert any(n in line for n in ("不", "沒有", "未", "無", "並非")), (name, line)


def test_user_decisions_cover_external_choices():
    t = text("USER_DECISIONS.md")
    for item in ("網域", "託管平台", "廣告帳戶", "金流", "聯絡方式", "費用", "授權"):
        assert item in t, item


def test_seo_checklist_records_actual_results():
    t = text("SEO_CHECKLIST.md")
    assert "BASE_URL" in t and "example.com" in t
    assert "通過" in t and "尚未" in t
