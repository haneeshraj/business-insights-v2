"""Tests for putting a page's evidence together."""

from bi2.core.models import PageKind
from bi2.evidence.build import build_evidence
from tests.factories import page_snapshot

CAFE = """<!doctype html>
<html><head><title>Example Cafe</title>
<meta property="og:site_name" content="Example Cafe"></head>
<body><header><a href="/"><img src="/logo.png" alt="Example Cafe logo"></a></header>
<main><p>Coffee and pastries.</p></main>
<footer>12 Queen St W, Toronto</footer></body></html>"""

DENIED = "<html><head><title>Access Denied</title></head><body>Access Denied</body></html>"


def test_evidence_from_a_loaded_page() -> None:
    ev = build_evidence(page_snapshot(CAFE))
    assert ev.page.kind is PageKind.OWN_WEBSITE
    assert ev.page.final_url == "https://example-cafe.ca/"
    assert ev.meta.site_name == "Example Cafe"


def test_a_refused_page_is_not_taken_for_the_business_site() -> None:
    ev = build_evidence(page_snapshot(DENIED, status_code=403))
    assert ev.page.kind is PageKind.UNKNOWN
