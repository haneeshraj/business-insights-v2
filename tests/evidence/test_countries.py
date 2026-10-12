"""Tests for the country data, postcodes and country hints."""

from bi2.evidence.countries import (
    countries,
    country_code,
    find_postcodes,
    guess_countries,
    page_languages,
)
from bi2.evidence.document import parse_html


def test_country_names_and_codes_give_the_code() -> None:
    assert country_code("Canada") == "CA"
    assert country_code("UK") == "GB"
    assert country_code("U.S.") == "US"
    assert country_code(" ca ") == "CA"
    assert country_code("fr") == "FR"
    assert country_code("Narnia") is None


def test_every_postcode_pattern_compiles() -> None:
    loaded = countries()
    assert {"CA", "US", "GB", "IE", "AU"} <= {code for code, c in loaded.items() if c.postcode}
    assert find_postcodes("") == []


def test_finds_distinctive_postcodes_in_order() -> None:
    text = (
        "Visit 128a Sterling Rd, Toronto ON M6R 2B7. Our Buffalo shop: 225 Delaware Ave, "
        "Buffalo, NY 14202. London: 1 High St, SW1A 1AA. Call 14202 or M6R 2B7 again."
    )
    assert find_postcodes(text) == [("M6R 2B7", "CA"), ("14202", "US"), ("SW1A 1AA", "GB")]


def test_a_zip_code_needs_its_state() -> None:
    assert find_postcodes("Order #14202 ships in 5 days") == []


def test_reads_the_page_languages() -> None:
    doc = parse_html(
        '<html lang="en-CA"><head><meta property="og:locale" content="en_CA"></head></html>'
    )
    assert page_languages(doc) == ["en-CA", "en_CA"]


def test_clues_add_up_to_the_most_likely_country() -> None:
    assert guess_countries("https://example-cafe.ca/") == ("CA",)
    assert guess_countries("https://example.co.uk/") == ("GB",)
    assert guess_countries("https://example.com/") == ()
    # A .com site that says it's in en-US, but has a Canadian address and phone number.
    canadian = guess_countries(
        "https://example.com/",
        languages=["en-US"],
        postcodes=[("M6R 2B7", "CA")],
        phone_countries=["CA"],
    )
    assert canadian == ("CA", "US")
    assert guess_countries("https://example.com/", address_country="IE")[0] == "IE"
