"""Tests for looking businesses up on Wikidata, answered without the network."""

import json
from typing import Any

import httpx
import pytest

from bi2.core.errors import LookupUnavailable
from bi2.services.wikidata import Wikidata


def _claim(value: Any, rank: str = "normal") -> dict[str, Any]:
    return {"rank": rank, "mainsnak": {"datavalue": {"value": value}}}


NO_FRILLS = {
    "labels": {"en": {"value": "No Frills"}},
    "claims": {
        "P856": [_claim("https://www.nofrills.ca/")],
        "P154": [_claim("No Frills logo.svg")],
        "P1329": [_claim("+1 866-987-6453")],
        "P2003": [_claim("nofrills")],
        "P2002": [_claim("old_account", rank="deprecated")],
    },
}


def _wikidata(entities: dict[str, Any], *, status: int = 200) -> Wikidata:
    """Wikidata answering searches with every item given, and their details."""

    def answer(request: httpx.Request) -> httpx.Response:
        if status != 200:
            return httpx.Response(status)
        if request.url.params["action"] == "query":
            hits = [{"title": item} for item in entities]
            return httpx.Response(200, json={"query": {"search": hits}})
        asked = request.url.params["ids"].split("|")
        found = {item: entities[item] for item in asked if item in entities}
        return httpx.Response(200, content=json.dumps({"entities": found}))

    return Wikidata(transport=httpx.MockTransport(answer))


async def test_a_business_is_found_by_its_official_website() -> None:
    async with _wikidata({"Q3342407": NO_FRILLS}) as wikidata:
        known = await wikidata.business_with_website("https://www.nofrills.ca/en")
    assert known is not None
    assert known.item == "Q3342407"
    assert known.name == "No Frills"
    assert (
        known.logo_url == "https://commons.wikimedia.org/wiki/Special:FilePath/No_Frills_logo.svg"
    )
    assert known.phone == "+1 866-987-6453"
    # A deprecated account is left out.
    assert [(p.platform, p.url) for p in known.social_links] == [
        ("instagram", "https://www.instagram.com/nofrills/")
    ]


async def test_an_item_whose_website_is_on_another_domain_isnt_the_business() -> None:
    other = {
        "labels": {"en": {"value": "Other"}},
        "claims": {"P856": [_claim("https://other.ca/")]},
    }
    async with _wikidata({"Q1": other}) as wikidata:
        assert await wikidata.business_with_website("https://www.nofrills.ca/") is None


async def test_no_matching_item_means_no_business() -> None:
    async with _wikidata({}) as wikidata:
        assert await wikidata.business_with_website("https://example-cafe.ca/") is None


async def test_wikidata_out_of_reach_is_said_so() -> None:
    async with _wikidata({}, status=503) as wikidata:
        with pytest.raises(LookupUnavailable):
            await wikidata.business_with_website("https://www.nofrills.ca/")
