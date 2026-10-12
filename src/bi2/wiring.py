"""Builds a RunContext from real implementations: `local_context` for the terminal app, and
later `hosted_context` for the website's workers.

This is where infrastructure is chosen and connected to the ports. Only entry points import
this module; logic and infrastructure never do.
"""

from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager
from pathlib import Path

from bi2.adapters.local.files import LocalFiles
from bi2.core.context import RunContext
from bi2.core.errors import FetchError
from bi2.core.models import PageSnapshot
from bi2.core.ports import Fetcher
from bi2.core.routing import load_routing
from bi2.core.settings import Settings
from bi2.fetch.browser import BrowserChoice, BrowserFetcher
from bi2.fetch.http import HttpDownloader


class _NoPages:
    """The fetcher for a run that analyzes saved pages and loads none."""

    async def fetch(self, url: str) -> PageSnapshot:
        raise FetchError(f"this run uses saved pages, so {url} isn't loaded")


@asynccontextmanager
async def local_context(
    out: Path,
    *,
    load_pages: bool = True,
    browser: BrowserChoice = "auto",
    timeout_s: float = 20.0,
    allow_private: bool = False,  # only for tests that serve pages from this machine
) -> AsyncIterator[RunContext]:
    """A RunContext for the terminal app: a browser, a downloader, and files under `out`.
    The browser closes when the block ends."""
    async with AsyncExitStack() as stack:
        fetcher: Fetcher = _NoPages()
        if load_pages:
            fetcher = await stack.enter_async_context(
                BrowserFetcher(timeout_s=timeout_s, browser=browser, allow_private=allow_private)
            )
        downloader = await stack.enter_async_context(HttpDownloader(allow_private=allow_private))
        yield RunContext(
            settings=Settings(),
            fetcher=fetcher,
            downloader=downloader,
            files=LocalFiles(out),
            routing=load_routing(),
        )
