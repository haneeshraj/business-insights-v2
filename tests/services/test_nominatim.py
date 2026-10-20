"""Tests for placing addresses on the map with Nominatim, answered without the network."""

import httpx
import pytest

from bi2.core.errors import LookupUnavailable
from bi2.core.models import Address
from bi2.services.nominatim import Nominatim

HIT = {
    "lat": "43.6655",
    "lon": "-79.3857",
    "display_name": "17, St Nicholas Street, Toronto, Ontario, M4Y 3G4, Canada",
    "address": {"postcode": "M4Y 3G4", "city": "Toronto", "state": "Ontario", "country_code": "ca"},
}
ADDRESS = Address(text="17 St Nicholas Street, Toronto, ON M4Y 3G4", country="CA")


async def test_an_address_is_placed_once(monkeypatch: pytest.MonkeyPatch) -> None:
    asked: list[httpx.Request] = []

    def answer(request: httpx.Request) -> httpx.Response:
        asked.append(request)
        return httpx.Response(200, json=[HIT])

    async with Nominatim(transport=httpx.MockTransport(answer)) as nominatim:
        place = await nominatim.locate(ADDRESS)
        again = await nominatim.locate(ADDRESS)
    assert place == again
    assert place is not None
    assert (place.coordinates.latitude, place.postal_code, place.country) == (
        43.6655,
        "M4Y 3G4",
        "CA",
    )
    assert len(asked) == 1
    assert asked[0].url.params["countrycodes"] == "ca"
    assert "bi2/" in asked[0].headers["user-agent"]


async def test_an_unknown_address_is_none_and_an_outage_says_so() -> None:
    async with Nominatim(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json=[]))
    ) as n:
        assert await n.locate(ADDRESS) is None
    async with Nominatim(transport=httpx.MockTransport(lambda r: httpx.Response(503))) as n:
        with pytest.raises(LookupUnavailable):
            await n.locate(ADDRESS)
