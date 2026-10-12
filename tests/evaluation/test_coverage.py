"""Tests for checking evidence against the gold set."""

from bi2.core.models import (
    Evidence,
    PageInfo,
    PageKind,
    PageMeta,
    StructuredData,
    TextRegions,
)
from bi2.evaluation.coverage import evidence_coverage, summarize
from bi2.evaluation.gold import ExpectedAddress, GoldSite

URL = "https://example-cafe.ca/"
CAFE = GoldSite(
    url=URL,
    category="cafe",
    company_names=("Example Cafe",),
    address=ExpectedAddress(street="128a Sterling Rd", city="Toronto", postal_code="M6R 2B7"),
    social_links=("https://instagram.com/examplecafe", "https://facebook.com/examplecafe"),
)


def _evidence(**parts: object) -> Evidence:
    page = PageInfo(url=URL, final_url=URL, kind=PageKind.OWN_WEBSITE)
    return Evidence.model_validate({"page": page, **parts})


def _checks(ev: Evidence) -> dict[str, tuple[bool, str]]:
    return {c.check: (c.found, c.where) for c in evidence_coverage(CAFE, ev)}


def test_a_name_can_be_found_in_part_of_the_title() -> None:
    checks = _checks(_evidence(meta=PageMeta(title="Menu | Example Cafe - Toronto")))
    assert checks["company_name"] == (True, "part of the title")
    assert checks["page_kind"] == (True, "own_website")


def test_social_links_need_every_expected_profile() -> None:
    one = StructuredData(same_as=("https://www.instagram.com/examplecafe/",))
    assert _checks(_evidence(structured=one))["social_links"] == (False, "")
    both = StructuredData(
        same_as=("https://www.instagram.com/examplecafe/", "https://m.facebook.com/ExampleCafe")
    )
    assert _checks(_evidence(structured=both))["social_links"] == (True, "")


def test_an_address_in_the_text_needs_its_lines_together() -> None:
    together = TextRegions(footer="Visit us\n128a Sterling Rd\nToronto, ON M6R 2B7")
    assert _checks(_evidence(text=together))["address (page text)"][0]
    apart = TextRegions(
        main="Order 128a for $5\n" + "Fresh bread\n" * 5, footer="Toronto, ON M6R 2B7"
    )
    assert not _checks(_evidence(text=apart))["address (page text)"][0]


def test_summary_counts_found_and_checked_sites() -> None:
    found = evidence_coverage(CAFE, _evidence(meta=PageMeta(site_name="Example Cafe")))
    missed = evidence_coverage(CAFE, _evidence(meta=PageMeta(site_name="Pinterest")))
    totals = summarize([found, missed])
    assert totals["company_name"] == (1, 2)
    assert totals["page_kind"] == (2, 2)
    assert "phone" not in totals  # the gold set doesn't list a phone for this site
