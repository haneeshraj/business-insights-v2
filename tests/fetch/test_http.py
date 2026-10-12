"""Tests for HttpDownloader, against the local test website."""

import pytest

from bi2.core.errors import FetchError, UnsafeUrl
from bi2.fetch.http import HttpDownloader
from tests.conftest import CAFE_PAGE, PNG


async def test_downloads_a_file_and_follows_redirects(site: str) -> None:
    async with HttpDownloader(allow_private=True) as downloader:
        assert await downloader.download(f"{site}/images/logo.png", max_bytes=10_000) == PNG
        assert await downloader.download(f"{site}/redirect", max_bytes=10_000) == CAFE_PAGE


async def test_files_larger_than_the_limit_are_refused(site: str) -> None:
    async with HttpDownloader(allow_private=True) as downloader:
        with pytest.raises(FetchError, match="larger than 10 bytes"):
            await downloader.download(f"{site}/images/logo.png", max_bytes=10)


async def test_missing_files_are_errors(site: str) -> None:
    async with HttpDownloader(allow_private=True) as downloader:
        with pytest.raises(FetchError, match="answered 404"):
            await downloader.download(f"{site}/nowhere.png", max_bytes=10_000)


async def test_private_addresses_are_refused_by_default(site: str) -> None:
    async with HttpDownloader() as downloader:
        with pytest.raises(UnsafeUrl, match="isn't on the public internet"):
            await downloader.download(f"{site}/images/logo.png", max_bytes=10_000)
