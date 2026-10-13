"""Tests for loading a page under the site's other name, with or without "www.", when its
security certificate is for that one.

No browser runs: page loading is replaced, since a test can't serve a real certificate for the
wrong name.
"""

from typing import Any

import pytest

from bi2.core.errors import FetchError, WrongCertificateName
from bi2.core.models import PageSnapshot
from bi2.fetch.browser import BrowserFetcher
from tests.factories import page_snapshot


def _fetcher(monkeypatch: pytest.MonkeyPatch, wrong_name: str, tried: list[str]) -> BrowserFetcher:
    """A fetcher whose pages load, except under `wrong_name`, whose certificate is for another
    name."""

    async def load(self: BrowserFetcher, started: Any, url: str) -> PageSnapshot:
        tried.append(url)
        if url == wrong_name:
            raise WrongCertificateName(
                f"couldn't load {url}: its security certificate is for another name"
            )
        return page_snapshot("<html><body>Kaya cake</body></html>", url=url)

    monkeypatch.setattr(BrowserFetcher, "_load", load)
    fetcher = BrowserFetcher(allow_private=True)
    monkeypatch.setattr(fetcher, "_main", object())  # stands in for a started browser
    return fetcher


@pytest.mark.parametrize(
    ("given", "other"),
    [
        ("https://www.example-bakery.sg/shop?page=2", "https://example-bakery.sg/shop?page=2"),
        ("https://example-bakery.sg/", "https://www.example-bakery.sg/"),
    ],
)
async def test_the_page_loads_under_the_name_its_certificate_is_for(
    monkeypatch: pytest.MonkeyPatch, given: str, other: str
) -> None:
    tried: list[str] = []
    snapshot = await _fetcher(monkeypatch, given, tried).fetch(given)
    assert tried == [given, other]
    assert (snapshot.url, snapshot.final_url) == (given, other)  # it's kept as the page asked for


async def test_other_errors_dont_switch_names(monkeypatch: pytest.MonkeyPatch) -> None:
    async def refuse(self: BrowserFetcher, started: Any, url: str) -> PageSnapshot:
        raise FetchError(f"couldn't load {url}: net::ERR_CONNECTION_RESET")

    monkeypatch.setattr(BrowserFetcher, "_load", refuse)
    fetcher = BrowserFetcher(allow_private=True)
    monkeypatch.setattr(fetcher, "_main", object())
    with pytest.raises(FetchError, match="CONNECTION_RESET"):
        await fetcher.fetch("https://www.example-bakery.sg/")


async def test_an_ip_address_has_no_other_name(monkeypatch: pytest.MonkeyPatch) -> None:
    tried: list[str] = []
    fetcher = _fetcher(monkeypatch, "https://203.0.113.7/", tried)
    with pytest.raises(WrongCertificateName):
        await fetcher.fetch("https://203.0.113.7/")
    assert tried == ["https://203.0.113.7/"]
