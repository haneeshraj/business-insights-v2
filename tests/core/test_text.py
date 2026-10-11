"""Tests for bi2.core.text."""

import pytest

from bi2.core.text import clean_space, fold, names_match, normalize_company_name


def test_clean_space_collapses_whitespace() -> None:
    assert clean_space("  SPoT \n Coffee\t") == "SPoT Coffee"


def test_fold_ignores_case_and_accents() -> None:
    assert fold("Café  ÉTOILE") == "cafe etoile"


@pytest.mark.parametrize(
    ("name", "key"),
    [
        ("Henderson Brewing Co.", "henderson brewing"),
        ("Henderson Brewing Company", "henderson brewing"),
        ("The Monarch Tavern", "monarch tavern"),
        ("Black Lab Brewing Inc", "black lab brewing"),
        ("Fromagerie Ltée", "fromagerie"),
        ("Smith & Sons L.L.C.", "smith and sons"),
        ("Grace O'Malley's", "grace o malley s"),
    ],
)
def test_normalize_company_name(name: str, key: str) -> None:
    assert normalize_company_name(name) == key


def test_names_match_across_spelling_differences() -> None:
    assert names_match("SPoT Coffee", "spot coffee")
    assert names_match("Henderson Brewing Co.", "Henderson Brewing Company")
    assert not names_match("Bar Volo", "Birreria Volo")


def test_empty_names_never_match() -> None:
    assert not names_match("", "")
    assert not names_match("Inc.", "Ltd.")
