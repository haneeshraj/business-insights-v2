"""Tests for putting a page's evidence together."""

from bi2.core.models import Box, PageKind, RenderedImage
from bi2.evidence.build import build_evidence
from tests.factories import page_snapshot

TOP = Box(x=20, y=10, width=100, height=30)

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


PROFILE_URL = "https://www.instagram.com/examplecafe/"
PROFILE = """<html><head>
<title>Example Cafe (@examplecafe) • Instagram photos and videos</title>
<meta property="og:site_name" content="Instagram"></head>
<body><header><a href="/">Instagram</a></header>
<main><h2>examplecafe</h2>
  <a href="https://l.instagram.com/?u=https%3A%2F%2Fexample-cafe.ca%2F&amp;e=AT0">example-cafe.ca</a>
  <a href="https://www.instagram.com/popular/">Popular</a>
</main>
<footer>&copy; 2026 Instagram from Meta</footer></body></html>"""


def test_a_platform_profile_gives_the_business_not_the_platform() -> None:
    images = [
        RenderedImage(kind="svg", alt="Instagram", in_header=True, links_home=True, box=TOP),
        RenderedImage(
            kind="img",
            url="https://scontent.cdninstagram.com/v/t51/examplecafe.jpg",
            alt="examplecafe's profile picture",
            box=Box(x=100, y=120, width=150, height=150),
        ),
    ]
    ev = build_evidence(page_snapshot(PROFILE, url=PROFILE_URL, images=images))
    assert ev.page.kind is PageKind.PLATFORM_PROFILE
    assert ev.page.platform == "instagram"
    assert ev.page.profile_name == "Example Cafe"
    assert ev.page.own_website == "https://example-cafe.ca/"
    assert [profile.url for profile in ev.social_links] == [PROFILE_URL]
    # The profile picture is the logo; the platform's own logo isn't a candidate at all.
    assert [c.alt for c in ev.logo_candidates] == ["examplecafe's profile picture"]
    assert ev.contact_pages == ()
    # The platform's own name and copyright line describe the platform, not the business.
    assert ev.meta.site_name == ""
    assert ev.contacts.copyright_line is None


def test_a_platform_page_that_isnt_a_profile_is_unknown() -> None:
    post = "https://www.instagram.com/p/C1a2b3c4/"
    assert build_evidence(page_snapshot(PROFILE, url=post)).page.kind is PageKind.UNKNOWN
