"""Countries: the entries in data/countries.toml, and turning a country's name into its code."""

import tomllib
from functools import cache
from importlib.resources import files

from pydantic import BaseModel, ConfigDict, Field

from bi2.core.models import CountryCode
from bi2.core.text import fold


class Country(BaseModel):
    """One entry in data/countries.toml."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    names: tuple[str, ...] = Field(min_length=1)
    domains: tuple[str, ...] = ()  # the last part of the country's web addresses, like "ca"


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
