"""A downloader that keeps every file it downloads, for runs on saved pages."""

import asyncio
import hashlib
from pathlib import Path

from bi2.core.ports import Downloader


class KeptDownloads:
    """Downloads each file once and keeps it in a folder, named by its address. Later runs get
    the kept copy, so runs on saved pages see the same files every time, and need no network
    once every file is kept."""

    def __init__(self, downloader: Downloader, folder: Path) -> None:
        self._downloader = downloader
        self._folder = folder

    async def download(self, url: str, *, max_bytes: int, referer: str | None = None) -> bytes:
        place = self._folder / hashlib.sha256(url.encode()).hexdigest()
        if await asyncio.to_thread(place.is_file):
            kept = await asyncio.to_thread(place.read_bytes)
            if len(kept) <= max_bytes:
                return kept
        data = await self._downloader.download(url, max_bytes=max_bytes, referer=referer)

        def keep() -> None:
            place.parent.mkdir(parents=True, exist_ok=True)
            place.write_bytes(data)

        await asyncio.to_thread(keep)
        return data
