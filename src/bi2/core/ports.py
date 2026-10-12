"""Interfaces for everything that does I/O. Logic depends on these; infrastructure implements
them; entry points choose which implementation to use."""

from typing import Protocol

from bi2.core.models import PageSnapshot


class Fetcher(Protocol):
    """Loads a page and captures what's needed to build its evidence."""

    async def fetch(self, url: str) -> PageSnapshot:
        """Load one page. Raises UnsafeUrl, PageTimeout or FetchError."""
        ...
