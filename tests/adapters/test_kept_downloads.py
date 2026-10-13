"""Tests for keeping downloads, for runs on saved pages."""

import asyncio
from pathlib import Path

import pytest

from bi2.adapters.local.downloads import KeptDownloads
from bi2.core.errors import FetchError
from tests.fakes import FakeDownloader

URL = "https://example-cafe.ca/logo.png"


def test_a_file_is_downloaded_once_and_kept(tmp_path: Path) -> None:
    online = FakeDownloader({URL: b"logo"})
    first = asyncio.run(KeptDownloads(online, tmp_path).download(URL, max_bytes=100))
    offline = FakeDownloader()  # every download fails, so only a kept copy will do
    again = asyncio.run(KeptDownloads(offline, tmp_path).download(URL, max_bytes=100))
    assert first == again == b"logo"
    assert (online.asked, offline.asked) == ([URL], [])


def test_a_kept_file_still_has_to_fit(tmp_path: Path) -> None:
    asyncio.run(
        KeptDownloads(FakeDownloader({URL: b"logo"}), tmp_path).download(URL, max_bytes=100)
    )
    with pytest.raises(FetchError):  # too big for this caller, so it's asked for again
        asyncio.run(KeptDownloads(FakeDownloader(), tmp_path).download(URL, max_bytes=2))
