"""Tests for the country data and country codes."""

from bi2.evidence.countries import countries, country_code


def test_country_names_and_codes_give_the_code() -> None:
    assert country_code("Canada") == "CA"
    assert country_code("UK") == "GB"
    assert country_code("U.S.") == "US"
    assert country_code(" ca ") == "CA"
    assert country_code("fr") == "FR"
    assert country_code("Narnia") is None


def test_every_country_in_the_data_file_has_a_valid_entry() -> None:
    loaded = countries()
    assert "CA" in loaded
    assert all(len(code) == 2 and code.isupper() for code in loaded)
