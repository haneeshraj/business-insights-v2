"""A knowledge base that keeps every answer it gets, for runs on saved pages."""

import asyncio
import json
from pathlib import Path

from bi2.core.models import KnownBusiness
from bi2.core.ports import KnowledgeBase
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
