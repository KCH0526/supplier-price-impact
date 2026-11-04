"""Public static website (web/): SEO, accessibility, privacy and honesty checks."""

import re
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"
BASE = "https://example.com/"
PAGES = sorted(WEB.rglob("*.html"))
REQUIRED = ["index.html", "features.html", "industries.html", "tools/index.html", "demo/index.html",
            "enterprise.html", "install.html", "faq.html", "privacy.html", "contact.html", "articles/index.html"]
TRACKERS = ["adsbygoogle", "googletagmanager", "google-analytics", "gtag(", "fbq(", "hotjar", "clarity.ms",
            "doubleclick", "pagead2"]
NETWORK_JS = ["fetch(", "XMLHttpRequest", "sendBeacon", "WebSocket", "localStorage", "sessionStorage",
              "document.cookie", "import(", "eval(", "new Function"]
CLAIMS = ["已有客戶", "客戶見證", "官方認證", "已獲認證", "保證獲利", "保證成交", "保證收益", "最佳價格", "已成交"]


class Page(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tags, self.title, self.text, self._in_title, self._skip = [], "", [], False, 0

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))
        if tag == "title":
            self._in_title = True
        if tag in ("script", "style"):
            self._skip += 1

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False
        if tag in ("script", "style"):
            self._skip -= 1

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        elif not self._skip:
            self.text.append(data)


def parse(path):
    p = Page()
    p.feed(path.read_text(encoding="utf-8"))
    return p


def rel(path):
    return path.relative_to(WEB).as_posix()


def test_required_pages_exist():
    names = {rel(p) for p in PAGES}
    for page in REQUIRED:
        assert page in names, page
    assert len([p for p in PAGES if p.parent.name == "articles" and p.name != "index.html"]) >= 6


def test_seo_and_accessibility_basics():
    titles, descriptions = set(), set()
    for path in PAGES:
        raw = path.read_text(encoding="utf-8")
        page = parse(path)
        assert raw.lower().startswith("<!doctype html>"), rel(path)
        html = next(a for t, a in page.tags if t == "html")
        assert html.get("lang") == "zh-Hant-TW", rel(path)
        metas = {a.get("name"): a.get("content") for t, a in page.tags if t == "meta" and a.get("name")}
        assert "width=device-width" in metas.get("viewport", ""), rel(path)
        assert 10 <= len(metas.get("description", "")) <= 160, rel(path)
        assert page.title.strip() and page.title not in titles, rel(path)
        assert metas["description"] not in descriptions, rel(path)
        titles.add(page.title)
        descriptions.add(metas["description"])
        assert any(t == "main" for t, _ in page.tags), rel(path)
        assert any(t == "a" and a.get("class") == "skip-link" for t, a in page.tags), rel(path)
        canonical = [a["href"] for t, a in page.tags if t == "link" and a.get("rel") == "canonical"]
        assert canonical == [BASE + ("" if rel(path) == "index.html" else rel(path))], rel(path)


def test_no_upload_no_forms_no_external_resources():
    for path in PAGES:
        page = parse(path)
        for tag, attrs in page.tags:
            assert tag != "form", rel(path)
            assert not (tag == "input" and attrs.get("type") == "file"), rel(path)
            if tag in ("script", "img", "iframe", "source"):
                src = attrs.get("src", "")
                assert not urlparse(src).scheme and not src.startswith("//"), (rel(path), src)
            assert tag != "iframe", rel(path)
            if tag == "link" and attrs.get("rel") != "canonical":
                href = attrs.get("href", "")
                assert not urlparse(href).scheme and not href.startswith("//"), (rel(path), href)


def test_no_trackers_ads_or_network_code():
    for path in [*PAGES, *WEB.rglob("*.js"), *WEB.rglob("*.css")]:
        text = path.read_text(encoding="utf-8")
        for word in TRACKERS:
            assert word not in text, (rel(path), word)
    for path in WEB.rglob("*.js"):
        text = path.read_text(encoding="utf-8")
        for word in NETWORK_JS:
            assert word not in text, (rel(path), word)


def test_internal_links_resolve():
    for path in PAGES:
        for tag, attrs in parse(path).tags:
            href = attrs.get("href") if tag in ("a", "link") else attrs.get("src") if tag in ("script", "img") else None
            if not href or href.startswith(("#", "mailto:")) or urlparse(href).scheme:
                continue
            target = (path.parent / href.split("#")[0]).resolve()
            if href.endswith("/"):
                target = target / "index.html"
            assert target.exists(), (rel(path), href)


def test_tool_inputs_are_labelled_and_results_announced():
    page = parse(WEB / "tools" / "index.html")
    ids = {a.get("for") for t, a in page.tags if t == "label"}
    inputs = [a for t, a in page.tags if t == "input"]
    assert len(inputs) >= 12
    assert all(a.get("id") in ids for a in inputs)
    assert sum(1 for t, a in page.tags if a.get("aria-live") == "polite") >= 4
    raw = (WEB / "tools" / "index.html").read_text(encoding="utf-8")
    assert "assets/calculators.js" in raw and "在您的瀏覽器" in raw


def test_sitemap_and_robots():
    sitemap = (WEB / "sitemap.xml").read_text(encoding="utf-8")
    urls = set(re.findall(r"<loc>(.*?)</loc>", sitemap))
    expected = {BASE + ("" if rel(p) == "index.html" else rel(p)) for p in PAGES if p.name != "404.html"}
    assert urls == expected
    robots = (WEB / "robots.txt").read_text(encoding="utf-8")
    assert f"Sitemap: {BASE}sitemap.xml" in robots and "User-agent: *" in robots


def test_articles_are_substantial_and_practical():
    for path in PAGES:
        if path.parent.name != "articles" or path.name == "index.html":
            continue
        page = parse(path)
        body = "".join(page.text)
        chinese = len(re.findall(r"[一-鿿]", body))
        # Proxy for substance (set to 700 after review; each article also needs sections, steps and an example).
        assert chinese >= 700, (rel(path), chinese)
        assert sum(1 for t, _ in page.tags if t == "h2") >= 3, rel(path)
        assert "例" in body and ("步驟" in body or "做法" in body), rel(path)


def test_no_unverified_claims():
    for path in PAGES:
        text = "".join(parse(path).text)
        for word in CLAIMS:
            for m in re.finditer(word, text):
                ctx = text[max(0, m.start() - 12): m.end() + 2]
                assert any(n in ctx for n in ("不", "沒有", "未", "無", "並非")), (rel(path), ctx)
