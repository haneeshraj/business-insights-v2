"""Interfaces for everything that does I/O. Logic depends on these; infrastructure implements
them; entry points choose which implementation to use."""

from typing import Protocol

from bi2.core.models import PageSnapshot


class Fetcher(Protocol):
    """Loads a page and captures what's needed to build its evidence."""

    async def fetch(self, url: str) -> PageSnapshot:
        """Load one page. Raises UnsafeUrl, PageTimeout or FetchError."""
        ...


class Downloader(Protocol):
    """Downloads a file, such as a logo, with the same safety checks as loading pages."""

    async def download(self, url: str, *, max_bytes: int, referer: str | None = None) -> bytes:
        """The file's content. Raises UnsafeUrl, or FetchError, including when the file is
        larger than max_bytes. The referer is the page the file is on, which some image hosts
        ask for."""
        ...


class FileStore(Protocol):
    """The files a run produces, such as screenshots and logos, at paths relative to the
    run's output folder, like "example-cafe.ca/logo.png"."""

    async def save(self, path: str, data: bytes) -> str:
        """Save a file, replacing one already there, and return its path."""
        ...

    async def read(self, path: str) -> bytes:
        """Read a file saved earlier."""
        ...
