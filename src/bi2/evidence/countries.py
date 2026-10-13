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
_POINTS: Final = {"address": 4, "domain": 3, "postcode": 2, "region": 2, "phone": 2, "language": 1}

# A place name as addresses write it before the province or state: "Toronto", "St. Catharines",
# "Montréal". Its second letter is lowercase, so all-caps text like "SHIPPING, ON" doesn't count.
_PLACE: Final = r"[A-Z](?:[a-z]|[^\x00-\x7F])[\w.'\-]*(?: [A-Z][\w.'\-]*)*"


class Country(BaseModel):
    """One entry in data/countries.toml."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    names: tuple[str, ...] = Field(min_length=1)
    domains: tuple[str, ...] = ()  # the last part of the country's web addresses, like "ca"
    languages: tuple[str, ...] = ()  # spoken mainly there, like "ko"; not "en", "es" or "fr"
    postcode: str | None = None  # a regular expression, for distinctive postcode formats only
    regions: tuple[str, ...] = ()  # provinces or states, as written after a city


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


@cache
def _region_patterns() -> tuple[tuple[str, re.Pattern[str]], ...]:
    patterns = []
    for code, country in countries().items():
        if country.regions:
            longest_first = sorted(country.regions, key=len, reverse=True)
            names = "|".join(re.escape(name) for name in longest_first)
            patterns.append((code, re.compile(rf"\b{_PLACE},\s+(?:{names})\b")))
    return tuple(patterns)


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


def find_region_countries(text: str) -> list[CountryCode]:
    """Countries whose provinces or states the text names after a place, the way addresses do:
    "Toronto, ON" or "Buffalo, New York". The most mentioned first."""
    mentions = Counter(code for code, pattern in _region_patterns() for _ in pattern.finditer(text))
    return [code for code, _ in mentions.most_common()]


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


def _language_countries(language: str) -> list[str]:
    """The countries a page's language points to: the one in its tag, like Canada for "en-CA",
    or else the country whose main language it is, like Korea for "ko"."""
    region = _language_region(language)
    if region:
        return [region]
    spoken = re.split(r"[-_]", language)[0].lower()
    return [code for code, country in countries().items() if spoken in country.languages]


def guess_countries(
    url: str,
    *,
    address_country: str | None = None,
    languages: Iterable[str] = (),
    postcodes: Iterable[tuple[str, str]] = (),
    regions: Iterable[str] = (),
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
    spoken = (code for language in languages for code in _language_countries(language))
    for code in dict.fromkeys(spoken):
        points[code] += _POINTS["language"]
    for code in dict.fromkeys(code for _, code in postcodes):
        points[code] += _POINTS["postcode"]
    for code in dict.fromkeys(regions):
        points[code] += _POINTS["region"]
    for code in dict.fromkeys(phone_countries):
        points[code] += _POINTS["phone"]
    return tuple(code for code, _ in points.most_common())
