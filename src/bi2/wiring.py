"""Builds a RunContext from real implementations: `local_context` for the terminal app, and
later `hosted_context` for the website's workers.

This is where infrastructure is chosen and connected to the ports. Only entry points import
this module; logic and infrastructure never do.
"""

from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager
from pathlib import Path

from bi2.adapters.local.downloads import KeptDownloads
from bi2.adapters.local.files import LocalFiles
from bi2.adapters.local.snapshots import SavedPages
from bi2.core.context import RunContext
from bi2.core.errors import FetchError
from bi2.core.models import PageSnapshot
from bi2.core.ports import Downloader, Fetcher
from bi2.core.settings import Settings
from bi2.fetch.browser import BrowserChoice, BrowserFetcher
from bi2.fetch.http import HttpDownloader


class _NoPages:
    """The fetcher for a run that loads no pages and has none saved."""

    async def fetch(self, url: str) -> PageSnapshot:
        raise FetchError(f"this run loads no pages, so {url} isn't loaded")


@asynccontextmanager
async def local_context(
    out: Path,
    *,
    load_pages: bool = True,
    browser: BrowserChoice = "auto",
    timeout_s: float = 20.0,
    allow_private: bool = False,  # only for tests that serve pages from this machine
    kept_downloads: Path | None = None,
    saved_pages: Path | None = None,
) -> AsyncIterator[RunContext]:
    """A RunContext for the terminal app: a browser, a downloader, and files under `out`.
    With `saved_pages` instead of loading pages, the pages saved in that folder are read, such
    as each site's contact page. With `kept_downloads`, every file downloaded is kept in that
    folder and reused on later runs. The browser closes when the block ends."""
    async with AsyncExitStack() as stack:
        fetcher: Fetcher = SavedPages(saved_pages) if saved_pages is not None else _NoPages()
        if load_pages:
            fetcher = await stack.enter_async_context(
                BrowserFetcher(timeout_s=timeout_s, browser=browser, allow_private=allow_private)
            )
        downloader: Downloader = await stack.enter_async_context(
            HttpDownloader(allow_private=allow_private)
        )
        if kept_downloads is not None:
            downloader = KeptDownloads(downloader, kept_downloads)
        yield RunContext(
            settings=Settings(), fetcher=fetcher, downloader=downloader, files=LocalFiles(out)
        )
