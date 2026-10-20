"""Tests for social media links and contact pages."""

from bi2.evidence.document import parse_html
from bi2.evidence.links import extract_contact_pages, extract_social_links

BASE = "https://example-cafe.ca/"

PAGE = parse_html(
    """<header>
      <a href="/about-us">About us</a> <a href="/menu">Menu</a> <a href="#top">Top</a>
      <a href="https://shop.example-cafe.ca/pages/contact">Get in touch</a>
    </header>
    <footer>
      <a href="https://www.instagram.com/examplecafe/">Instagram</a>
      <a href="https://instagram.com/ExampleCafe">Instagram again</a>
      <a href="https://www.facebook.com/sharer/sharer.php?u=https://example-cafe.ca">Share</a>
      <a href="https://twitter.com/examplecafe">X</a>
      <a href="https://www.yelp.ca/biz/example-cafe-toronto">Yelp</a>
      <a href="/find-us">Visit us</a>
      <a href="https://other-cafe.ca/contact">A friend's cafe</a>
    </footer>"""
)


def test_social_links_are_profiles_listed_first_then_linked() -> None:
    profiles = extract_social_links(
        PAGE, BASE, listed=["https://www.tiktok.com/@examplecafe", "https://example-cafe.ca/"]
    )
    assert [(p.platform, p.url) for p in profiles] == [
        ("tiktok", "https://www.tiktok.com/@examplecafe"),
        ("instagram", "https://www.instagram.com/examplecafe/"),
        ("x", "https://twitter.com/examplecafe"),
    ]


def test_contact_pages_are_the_sites_own_pages_best_first() -> None:
    # A page named for contact details comes before ones that only might hold them.
    assert extract_contact_pages(PAGE, BASE) == (
        "https://shop.example-cafe.ca/pages/contact",
        "https://example-cafe.ca/about-us",
        "https://example-cafe.ca/find-us",
    )


def test_a_link_saying_contact_counts_as_much_as_a_contact_address() -> None:
    page = parse_html('<a href="/about-our-farm">About our farm</a> <a href="/help">Contact us</a>')
    assert extract_contact_pages(page, BASE)[0] == "https://example-cafe.ca/help"


def test_pages_for_one_purpose_and_teasers_are_never_the_contact_page() -> None:
    page = parse_html(
        '<a href="/about-us/press-enquiries">Press enquiries</a>'
        '<a href="/franchising/contact-our-team">Own a franchise</a>'
        '<a href="/blog/how-to-contact-a-roaster">Blog</a>'
        '<a href="/pages/pickup">Order online and pick up in store, ready in two hours</a>'
    )
    assert extract_contact_pages(page, BASE) == ()


def test_legal_pages_put_the_privacy_policy_first() -> None:
    from bi2.evidence.document import parse_html
    from bi2.evidence.links import extract_legal_pages

    doc = parse_html(
        '<footer><a href="/terms">Terms of use</a> <a href="/privacy-policy">Privacy</a>'
        ' <a href="https://other.example/privacy">Partner privacy</a></footer>'
    )
    assert extract_legal_pages(doc, "https://example-cafe.ca/") == (
        "https://example-cafe.ca/privacy-policy",
        "https://example-cafe.ca/terms",
    )
