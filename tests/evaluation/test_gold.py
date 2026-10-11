"""Tests for reading and checking the gold file."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from bi2.core.models import PageKind
from bi2.evaluation.gold import ExpectedAddress, GoldSite, load_gold_set, site_key

GOLD = """
[[site]]
url = "https://www.example-cafe.ca/"
category = "cafe"
confirmed = true
company_names = ["Example Cafe"]
logo_urls = ["https://www.example-cafe.ca/logo.png"]
mcc_codes = ["5814", "5812"]
address = { street = "12 Queen St W", city = "Toronto", postal_code = "M5H 2N2", country = "CA" }

[[site]]
url = "https://www.pinterest.com/examplecafe/"
category = "cafe"
page_kind = "platform_profile"
platform = "pinterest"
company_names = ["Example Cafe"]
address = "none"
"""


def _write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "gold.toml"
    path.write_text(text, encoding="utf-8")
    return path


def test_loads_sites_with_their_accepted_answers(tmp_path: Path) -> None:
    gold = load_gold_set(_write(tmp_path, GOLD))
    cafe, profile = gold.sites
    assert cafe.mcc_codes == ("5814", "5812")
    assert isinstance(cafe.address, ExpectedAddress)
    assert cafe.address.postal_code == "M5H 2N2"
    assert profile.page_kind is PageKind.PLATFORM_PROFILE
    assert profile.address == "none"
    assert profile.logo_urls is None  # not checked


def test_rejects_a_site_listed_twice(tmp_path: Path) -> None:
    twice = GOLD + '\n[[site]]\nurl = "http://example-cafe.ca"\ncategory = "cafe"\n'
    with pytest.raises(ValidationError, match="more than once"):
        load_gold_set(_write(tmp_path, twice))


def test_rejects_unknown_top_level_keys(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="unknown top-level keys"):
        load_gold_set(_write(tmp_path, "version = 1\n" + GOLD))


def test_platform_profiles_need_a_platform() -> None:
    with pytest.raises(ValidationError, match="need a platform name"):
        GoldSite(
            url="https://www.pinterest.com/examplecafe/",
            category="cafe",
            page_kind=PageKind.PLATFORM_PROFILE,
        )


def test_gold_phones_must_be_e164() -> None:
    with pytest.raises(ValidationError, match="should match pattern"):
        GoldSite(url="https://example-bar.ca/", category="bar", phones=("416-555-0123",))


def test_an_expected_address_needs_enough_to_compare() -> None:
    with pytest.raises(ValidationError, match="postal code, or a street and a city"):
        ExpectedAddress(street="12 Queen St W")


def test_site_key_ignores_scheme_www_and_trailing_slash() -> None:
    assert site_key("https://www.Example-Cafe.ca/") == site_key("http://example-cafe.ca")
    assert site_key("https://example-cafe.ca/menu/") != site_key("https://example-cafe.ca/")
