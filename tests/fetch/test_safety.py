"""Tests for the URL safety check, with fake DNS lookups so they need no network."""

import socket

import pytest

from bi2.core.errors import FetchError, UnsafeUrl
from bi2.fetch.safety import Resolver, ensure_public_url, host_is_public


def _resolves_to(*addresses: str) -> Resolver:
    async def resolve(host: str) -> list[str]:
        return list(addresses)

    return resolve


async def _no_such_host(host: str) -> list[str]:
    raise socket.gaierror("no such host")


async def test_public_hosts_are_allowed() -> None:
    await ensure_public_url("https://example-cafe.ca/menu", _resolves_to("93.184.216.34"))


@pytest.mark.parametrize(
    "url", ["ftp://example-cafe.ca/", "file:///etc/passwd", "javascript:alert(1)", "https://"]
)
async def test_only_web_urls_are_allowed(url: str) -> None:
    with pytest.raises(UnsafeUrl, match="only http and https"):
        await ensure_public_url(url, _resolves_to("93.184.216.34"))


@pytest.mark.parametrize(
    "addresses", [("10.0.0.5",), ("169.254.169.254",), ("93.184.216.34", "127.0.0.1")]
)
async def test_hosts_that_reach_private_addresses_are_refused(addresses: tuple[str, ...]) -> None:
    with pytest.raises(UnsafeUrl, match="isn't on the public internet"):
        await ensure_public_url("https://example-cafe.ca/", _resolves_to(*addresses))


async def test_hosts_that_dont_exist_are_reported_as_not_found() -> None:
    with pytest.raises(FetchError, match=r"couldn't find example-cafe\.ca"):
        await ensure_public_url("https://example-cafe.ca/", _no_such_host)


async def test_host_is_public_is_false_for_hosts_that_dont_resolve() -> None:
    assert not await host_is_public("example-cafe.ca", _no_such_host)
    assert not await host_is_public("", _resolves_to("93.184.216.34"))
