"""The gold set: sites with known answers, used to measure accuracy, cost and speed.

The gold file is TOML, with one `[[site]]` table per site. For each field:
- leaving the key out means the field isn't checked for that site,
- the text "none" means the site has no such thing, so finding nothing is correct,
- otherwise the key lists the accepted answers, and any one of them is correct.
"""

import tomllib
from pathlib import Path
from typing import Annotated, Literal, Self
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, model_validator

from bi2.core.models import CountryCode, EmailAddress, MccCode, PageKind, PhoneNumber, WebUrl


class _Strict(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


def site_key(url: str) -> str:
    """A key that treats `https://www.example.com/` and `http://example.com` as the same site."""
    parts = urlsplit(url.strip())
    return parts.netloc.casefold().removeprefix("www.") + parts.path.rstrip("/").casefold()


class ExpectedAddress(_Strict):
    """The parts of an address that decide whether an answer is correct."""

    street: str | None = None  # for example "225 Delaware Avenue"; its house number is checked
    city: str | None = None
    postal_code: str | None = None
    country: CountryCode | None = None

    @model_validator(mode="after")
    def _enough_to_compare(self) -> Self:
        if not self.postal_code and not (self.street and self.city):
            raise ValueError("an expected address needs a postal code, or a street and a city")
        return self


class GoldSite(_Strict):
    """One site in the gold set, with the answers v2 should give."""

    url: WebUrl
    category: str = Field(min_length=1)  # for example "cafe" or "bookstore"
    confirmed: bool = False  # a person has checked these answers
    page_kind: PageKind = PageKind.OWN_WEBSITE
    platform: str | None = None
    company_names: Annotated[tuple[str, ...], Field(min_length=1)] | None = None
    logo_urls: Annotated[tuple[WebUrl, ...], Field(min_length=1)] | Literal["none"] | None = None
    mcc_codes: Annotated[tuple[MccCode, ...], Field(min_length=1)] | None = None
    address: ExpectedAddress | Literal["none"] | None = None
    # E.164 format, such as "+14165550123"; list every number that counts as correct.
    phones: Annotated[tuple[PhoneNumber, ...], Field(min_length=1)] | Literal["none"] | None = None
    # Lowercase; list every address that counts as correct.
    emails: Annotated[tuple[EmailAddress, ...], Field(min_length=1)] | Literal["none"] | None = None
    # The business's own profiles; a result is correct when it finds all of them.
    social_links: Annotated[tuple[WebUrl, ...], Field(min_length=1)] | Literal["none"] | None = None
    notes: str = ""

    @model_validator(mode="after")
    def _platform_matches_kind(self) -> Self:
        if (self.page_kind is PageKind.PLATFORM_PROFILE) != (self.platform is not None):
            raise ValueError("platform profiles, and only they, need a platform name")
        return self


class GoldSet(_Strict):
    """Every site in the gold file."""

    sites: tuple[GoldSite, ...]

    @model_validator(mode="after")
    def _each_site_once(self) -> Self:
        keys = [site_key(site.url) for site in self.sites]
        duplicates = sorted({key for key in keys if keys.count(key) > 1})
        if duplicates:
            raise ValueError(f"sites listed more than once: {duplicates}")
        return self


def load_gold_set(path: Path) -> GoldSet:
    """Read and check a gold file."""
    with path.open("rb") as file:
        data = tomllib.load(file)
    unknown = set(data) - {"site"}
    if unknown:
        raise ValueError(f"unknown top-level keys in {path.name}: {sorted(unknown)}")
    return GoldSet.model_validate({"sites": data.get("site", [])})
