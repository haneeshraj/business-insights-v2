"""Wikidata, a free public knowledge base, as v2's knowledge base: it knows big businesses by
the official website they list there.

A lookup is two requests to Wikidata's own API: a search for items whose official website is
the site's address, however it's written, then those items' details. The first item whose
website is on the site's domain is the business. Wikimedia asks every client to say who it is,
so the requests do.
"""

from types import TracebackType
from typing import Any, Final, Self
from urllib.parse import quote

import httpx

from bi2 import USER_AGENT
from bi2.core.errors import LookupUnavailable
from bi2.core.models import KnownBusiness, SocialProfile
from bi2.core.urls import registrable_domain

_API: Final = "https://www.wikidata.org/w/api.php"
_COMMONS_FILE: Final = "https://commons.wikimedia.org/wiki/Special:FilePath/"
_HEADERS: Final = {"User-Agent": USER_AGENT}
# Wikidata's properties for an official website, a logo image, a phone number and an email.
_WEBSITE, _LOGO, _PHONE, _EMAIL = "P856", "P154", "P1329", "P968"
# Its properties for accounts on platforms, and each account's address.
_ACCOUNTS: Final = {
    "P2002": ("x", "https://x.com/{}"),
    "P2003": ("instagram", "https://www.instagram.com/{}/"),
    "P2013": ("facebook", "https://www.facebook.com/{}"),
    "P2397": ("youtube", "https://www.youtube.com/channel/{}"),
    "P4264": ("linkedin", "https://www.linkedin.com/company/{}/"),
    "P7085": ("tiktok", "https://www.tiktok.com/@{}"),
    "P3836": ("pinterest", "https://www.pinterest.com/{}/"),
}
_LABEL_LANGUAGES: Final = ("en", "fr", "es", "de", "it", "pt", "nl")
_MOST_ITEMS: Final = 5


def _addresses(domain: str) -> list[str]:
    """The ways a site's home page is usually written as an official website."""
    return [
        f"{scheme}://{www}{domain}{slash}"
        for scheme in ("https", "http")
        for www in ("www.", "")
        for slash in ("/", "")
    ]


def _values(claims: dict[str, Any], prop: str) -> list[Any]:
    """A property's values, leaving out deprecated ones."""
    return [
        snak["datavalue"]["value"]
        for claim in claims.get(prop, [])
        if claim.get("rank") != "deprecated" and "datavalue" in (snak := claim.get("mainsnak", {}))
    ]


def _first(claims: dict[str, Any], prop: str) -> str:
    return next((value for value in _values(claims, prop) if isinstance(value, str)), "")


def _business(item: str, entity: dict[str, Any]) -> KnownBusiness:
    claims = entity.get("claims", {})
    labels = entity.get("labels", {})
    name = next(
        (labels[language]["value"] for language in _LABEL_LANGUAGES if language in labels),
        next((label["value"] for label in labels.values()), ""),
    )
    logo = _first(claims, _LOGO)
    accounts = [
        SocialProfile(platform=platform, url=pattern.format(quote(value, safe="@._-")))
        for prop, (platform, pattern) in _ACCOUNTS.items()
        for value in _values(claims, prop)[:1]
        if isinstance(value, str) and value
    ]
    return KnownBusiness(
        item=item,
        name=name,
        logo_url=_COMMONS_FILE + quote(logo.replace(" ", "_")) if logo else None,
        phone=_first(claims, _PHONE),
        email=_first(claims, _EMAIL).removeprefix("mailto:"),
        social_links=tuple(accounts),
    )


class Wikidata:
    """Looks businesses up on Wikidata by their official websites. Each site is looked up once
    per run."""

    def __init__(
        self, *, timeout_s: float = 10.0, transport: httpx.AsyncBaseTransport | None = None
    ) -> None:
        self._timeout_s = timeout_s
        self._transport = transport  # for tests, which answer without the network
        self._client: httpx.AsyncClient | None = None
        self._found: dict[str, KnownBusiness | None] = {}

    async def __aenter__(self) -> Self:
        self._client = httpx.AsyncClient(
            timeout=self._timeout_s, headers=_HEADERS, transport=self._transport
        )
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if self._client:
            await self._client.aclose()

    async def _get(self, params: dict[str, str]) -> dict[str, Any]:
        if self._client is None:
            raise RuntimeError("use Wikidata inside an `async with` block")
        try:
            response = await self._client.get(_API, params={**params, "format": "json"})
            response.raise_for_status()
            data: dict[str, Any] = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise LookupUnavailable(f"Wikidata couldn't be reached: {exc}") from exc
        return data

    async def business_with_website(self, url: str) -> KnownBusiness | None:
        """The business whose official website is on this site's domain. Raises
        LookupUnavailable when Wikidata can't be reached."""
        domain = registrable_domain(url)
        if domain not in self._found:
            self._found[domain] = await self._look_up(domain)
        return self._found[domain]

    async def _look_up(self, domain: str) -> KnownBusiness | None:
        websites = "|".join(f"{_WEBSITE}={address}" for address in _addresses(domain))
        found = await self._get(
            {
                "action": "query",
                "list": "search",
                "srsearch": f"haswbstatement:{websites}",
                "srlimit": str(_MOST_ITEMS),
            }
        )
        items = [hit["title"] for hit in found.get("query", {}).get("search", [])]
        if not items:
            return None
        details = await self._get(
            {
                "action": "wbgetentities",
                "ids": "|".join(items),
                "props": "labels|claims",
                "languages": "|".join(_LABEL_LANGUAGES),
            }
        )
        entities = details.get("entities", {})
        for item in items:
            entity = entities.get(item, {})
            listed = _values(entity.get("claims", {}), _WEBSITE)
            if any(registrable_domain(site) == domain for site in listed if isinstance(site, str)):
                return _business(item, entity)
        return None
