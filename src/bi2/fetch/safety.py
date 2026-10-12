"""Checks that a URL is safe to fetch: http or https, on a host that only resolves to public
addresses. This stops a page, or a user of the website, from making v2 reach private networks."""

import asyncio
import socket
from collections.abc import Awaitable, Callable
from urllib.parse import urlsplit

from bi2.core.errors import FetchError, UnsafeUrl
from bi2.core.netsafety import is_public_address

Resolver = Callable[[str], Awaitable[list[str]]]


async def system_resolver(host: str) -> list[str]:
    """Every IP address a hostname resolves to, using the operating system's DNS."""
    infos = await asyncio.get_running_loop().getaddrinfo(host, None, type=socket.SOCK_STREAM)
    return sorted({str(info[4][0]) for info in infos})


async def host_is_public(host: str, resolver: Resolver = system_resolver) -> bool:
    """Whether every address the host resolves to is public. A host that doesn't resolve isn't."""
    if not host:
        return False
    try:
        addresses = await resolver(host)
    except OSError:
        return False
    return bool(addresses) and all(is_public_address(address) for address in addresses)


async def ensure_public_url(url: str, resolver: Resolver = system_resolver) -> None:
    """Raise UnsafeUrl unless the URL is http or https on a public host, or FetchError if the
    host can't be found."""
    parts = urlsplit(url)
    host = parts.hostname
    if parts.scheme not in ("http", "https") or not host:
        raise UnsafeUrl(f"only http and https URLs can be analyzed: {url}")
    try:
        addresses = await resolver(host)
    except OSError as exc:
        raise FetchError(f"couldn't find {host}") from exc
    if not addresses or not all(is_public_address(address) for address in addresses):
        raise UnsafeUrl(f"{host} isn't on the public internet")
