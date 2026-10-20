"""A knowledge base and a geocoder that keep every answer they get, for runs on saved
pages."""

import asyncio
import hashlib
import json
from pathlib import Path

from bi2.core.models import Address, GeocodedPlace, KnownBusiness
from bi2.core.ports import Geocoder, KnowledgeBase
from bi2.core.urls import registrable_domain


class KeptLookups:
    """Looks each site up once and keeps the answer in a folder, named by the site's domain,
    "no such business" included. Later runs get the kept answer, so runs on saved pages see the
    same facts every time. A knowledge base that can't be reached keeps nothing."""

    def __init__(self, knowledge: KnowledgeBase, folder: Path) -> None:
        self._knowledge = knowledge
        self._folder = folder

    async def business_with_website(self, url: str) -> KnownBusiness | None:
        place = self._folder / f"{registrable_domain(url)}.json"
        if await asyncio.to_thread(place.is_file):
            kept = json.loads(await asyncio.to_thread(place.read_text, encoding="utf-8"))
            return KnownBusiness.model_validate(kept) if kept else None
        found = await self._knowledge.business_with_website(url)
        text = found.model_dump_json(indent=2) if found else "null"

        def keep() -> None:
            place.parent.mkdir(parents=True, exist_ok=True)
            place.write_text(text, encoding="utf-8", newline="\n")

        await asyncio.to_thread(keep)
        return found


class KeptPlaces:
    """Places each address on the map once and keeps the answer in a folder, "not on the map"
    included, so runs on saved pages see the same places every time."""

    def __init__(self, geocoder: Geocoder, folder: Path) -> None:
        self._geocoder = geocoder
        self._folder = folder

    async def locate(self, address: Address) -> GeocodedPlace | None:
        key = hashlib.sha256(address.text.encode()).hexdigest()[:24]
        place = self._folder / f"{key}.json"
        if await asyncio.to_thread(place.is_file):
            kept = json.loads(await asyncio.to_thread(place.read_text, encoding="utf-8"))
            return GeocodedPlace.model_validate(kept["place"]) if kept["place"] else None
        found = await self._geocoder.locate(address)
        text = json.dumps(
            {"address": address.text, "place": found.model_dump(mode="json") if found else None},
            indent=2,
        )

        def keep() -> None:
            place.parent.mkdir(parents=True, exist_ok=True)
            place.write_text(text, encoding="utf-8", newline="\n")

        await asyncio.to_thread(keep)
        return found
