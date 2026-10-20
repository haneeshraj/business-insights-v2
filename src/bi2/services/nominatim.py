"""OpenStreetMap's Nominatim, as v2's Geocoder: an address's place on the map.

Nominatim is free and needs no key, and asks every client to send at most one request a
second, to say who it is, and to keep what it learns, so it never asks twice for the same
address. Its usage policy: https://operations.osmfoundation.org/policies/nominatim/
"""

import asyncio
import time
from types import TracebackType
from typing import Any, Final, Self

import httpx

from bi2 import USER_AGENT
from bi2.core.errors import LookupUnavailable
from bi2.core.models import Address, Coordinates, GeocodedPlace

_API: Final = "https://nominatim.openstreetmap.org/search"
_GAP_S: Final = 1.1  # a little over the one second Nominatim asks for between requests


class Nominatim:
    """Looks addresses up on Nominatim, one request at a time, each address once per run."""

    def __init__(
        self, *, timeout_s: float = 15.0, transport: httpx.AsyncBaseTransport | None = None
    ) -> None:
        self._timeout_s = timeout_s
        self._transport = transport  # for tests, which answer without the network
        self._client: httpx.AsyncClient | None = None
        self._turn = asyncio.Lock()
        self._last = 0.0
        self._found: dict[str, GeocodedPlace | None] = {}

    async def __aenter__(self) -> Self:
        self._client = httpx.AsyncClient(
            timeout=self._timeout_s, headers={"User-Agent": USER_AGENT}, transport=self._transport
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

    async def _search(self, params: dict[str, str]) -> list[dict[str, Any]]:
        if self._client is None:
            raise RuntimeError("use Nominatim inside an `async with` block")
        async with self._turn:
            wait = self._last + _GAP_S - time.monotonic()
            if wait > 0:
                await asyncio.sleep(wait)
            try:
                response = await self._client.get(
                    _API, params={**params, "format": "jsonv2", "addressdetails": "1", "limit": "1"}
                )
                response.raise_for_status()
                found = response.json()
            except (httpx.HTTPError, ValueError) as exc:
                raise LookupUnavailable(f"Nominatim couldn't be reached: {exc}") from exc
            finally:
                self._last = time.monotonic()
        return found if isinstance(found, list) else []

    async def locate(self, address: Address) -> GeocodedPlace | None:
        """The place the address is at, or None when the map doesn't know it. Raises
        LookupUnavailable when Nominatim can't be reached."""
        if address.text not in self._found:
            self._found[address.text] = await self._look_up(address)
        return self._found[address.text]

    async def _look_up(self, address: Address) -> GeocodedPlace | None:
        country = {"countrycodes": address.country.lower()} if address.country else {}
        found = await self._search({"q": address.text, **country})
        if not found and address.street and (address.postal_code or address.city):
            structured = {
                "street": address.street,
                "city": address.city or "",
                "postalcode": address.postal_code or "",
            }
            found = await self._search({k: v for k, v in structured.items() if v} | country)
        if not found:
            return None
        hit = found[0]
        parts = hit.get("address", {})
        return GeocodedPlace(
            coordinates=Coordinates(latitude=float(hit["lat"]), longitude=float(hit["lon"])),
            postal_code=parts.get("postcode"),
            city=parts.get("city") or parts.get("town") or parts.get("village"),
            region=parts.get("state") or parts.get("province"),
            country=str(parts["country_code"]).upper() if parts.get("country_code") else None,
            source=f"OpenStreetMap: {str(hit.get('display_name', ''))[:200]}",
        )
