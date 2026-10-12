"""Countries: the entries in data/countries.toml, postcodes, and which countries a page points
to. Phone numbers and addresses are read differently in each country, so this comes first."""

import re
import tomllib
from collections import Counter
from collections.abc import Iterable
from functools import cache
from importlib.resources import files
from typing import Final

from pydantic import BaseModel, ConfigDict, Field

from bi2.core.models import CountryCode
from bi2.core.text import clean_space, fold
from bi2.core.urls import public_suffix
from bi2.evidence.document import Document, attribute

# How much each clue counts toward a country.
_POINTS: Final = {"address": 4, "domain": 3, "postcode": 2, "phone": 2, "language": 1}


class Country(BaseModel):
    """One entry in data/countries.toml."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    names: tuple[str, ...] = Field(min_length=1)
    domains: tuple[str, ...] = ()  # the last part of the country's web addresses, like "ca"
    postcode: str | None = None  # a regular expression, for distinctive postcode formats only


@cache
def countries() -> dict[str, Country]:
    """Every country in data/countries.toml, by ISO code."""
    text = files("bi2.data").joinpath("countries.toml").read_text(encoding="utf-8")
    data = tomllib.loads(text)
    data.pop("version")
    return {code: Country.model_validate(entry) for code, entry in data.items()}


@cache
def _codes_by_name() -> dict[str, str]:
    return {
        fold(name): code for code, country in countries().items() for name in (code, *country.names)
    }


@cache
def _postcode_patterns() -> tuple[tuple[str, re.Pattern[str]], ...]:
    return tuple(
        (code, re.compile(country.postcode))
        for code, country in countries().items()
        if country.postcode
    )


def country_code(text: str) -> CountryCode | None:
    """The ISO code for a country written as a code or a name: "CA", "Canada" and "UK" all
    work. Codes for countries not in the data file are accepted as they are."""
    code = _codes_by_name().get(fold(text))
    if code:
        return code
    text = text.strip()
    if len(text) == 2 and text.isascii() and text.isalpha():
        return text.upper()
    return None


def find_postcodes(text: str) -> list[tuple[str, CountryCode]]:
    """Postcodes in the text, each with its country, in the order they appear. Only formats
    distinctive enough not to be mistaken for other numbers are looked for."""
    found: list[tuple[int, str, str]] = []
    for code, pattern in _postcode_patterns():
        for match in pattern.finditer(text):
            group = "postcode" if "postcode" in pattern.groupindex else 0
            found.append((match.start(group), clean_space(match.group(group)), code))
    return list(dict.fromkeys((postcode, code) for _, postcode, code in sorted(found)))


def page_languages(doc: Document) -> list[str]:
    """The languages the page says it's in, like "en-CA", from its html tag and meta tags."""
    nodes = doc.css(
        'html[lang], meta[property="og:locale" i], meta[http-equiv="content-language" i]'
    )
    return [
        value for node in nodes if (value := attribute(node, "lang") or attribute(node, "content"))
    ]


def _language_region(language: str) -> str | None:
    """The country in a language tag: "en-CA" and "en_CA" give "CA"; "en" gives nothing."""
    parts = re.split(r"[-_]", language)
    region = next((part for part in parts[1:] if len(part) == 2 and part.isalpha()), None)
    return region.upper() if region else None


def guess_countries(
    url: str,
    *,
    address_country: str | None = None,
    languages: Iterable[str] = (),
    postcodes: Iterable[tuple[str, str]] = (),
    phone_countries: Iterable[str] = (),
) -> tuple[CountryCode, ...]:
    """The countries the business is most likely in, most likely first, from the clues on its
    page. Pages with no clues give none."""
    points: Counter[str] = Counter()
    ending = public_suffix(url).rsplit(".", 1)[-1]
    for code, country in countries().items():
        if ending in country.domains:
            points[code] += _POINTS["domain"]
    if address_country:
        points[address_country] += _POINTS["address"]
    # Each clue counts once per country, however often it appears. dict.fromkeys keeps the
    # order the clues were found in, which settles ties.
    regions = (region for language in languages if (region := _language_region(language)))
    for code in dict.fromkeys(regions):
        points[code] += _POINTS["language"]
    for code in dict.fromkeys(code for _, code in postcodes):
        points[code] += _POINTS["postcode"]
    for code in dict.fromkeys(phone_countries):
        points[code] += _POINTS["phone"]
    return tuple(code for code, _ in points.most_common())
