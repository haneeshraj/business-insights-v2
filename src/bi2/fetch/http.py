"""Downloading files, such as logos, over plain HTTP, with the same safety checks as pages."""

from types import TracebackType
from typing import Final, Self
from urllib.parse import urljoin

import httpx

from bi2 import __version__
from bi2.core.errors import FetchError
from bi2.fetch.safety import Resolver, ensure_public_url, system_resolver

_MAX_REDIRECTS: Final = 5
_REDIRECTS: Final = frozenset({301, 302, 303, 307, 308})
_HEADERS: Final = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
        f"Chrome/140.0.0.0 Safari/537.36 bi2/{__version__}"
    ),
    "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
}


class HttpDownloader:
    """Downloads files without a browser.

    Every address, including each redirect, is checked before it's requested, so a page can't
    point v2 at a private network. (The address is looked up again when connecting, so a
    domain that changes its address in between isn't caught; the browser has the same gap.)
    """

    def __init__(
        self,
        *,
        timeout_s: float = 10.0,
        allow_private: bool = False,  # only for tests that serve files from this machine
        resolver: Resolver = system_resolver,
    ) -> None:
        self._timeout_s = timeout_s
        self._allow_private = allow_private
        self._resolver = resolver
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> Self:
        # Redirects are followed by hand, so each one is checked first.
        self._client = httpx.AsyncClient(
            timeout=self._timeout_s, follow_redirects=False, headers=_HEADERS
        )
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if self._client:
            await self._client.aclose()

    async def download(self, url: str, *, max_bytes: int, referer: str | None = None) -> bytes:
        """The file at a URL. Raises UnsafeUrl, or FetchError, including when the file is
        larger than max_bytes."""
        if self._client is None:
            raise RuntimeError("use HttpDownloader inside an `async with` block")
        headers = {"Referer": referer} if referer else {}
        for _ in range(_MAX_REDIRECTS + 1):
            if not self._allow_private:
                await ensure_public_url(url, self._resolver)
            try:
                async with self._client.stream("GET", url, headers=headers) as response:
                    location = response.headers.get("location")
                    if response.status_code in _REDIRECTS and location:
                        url = urljoin(url, location)
                        continue
                    if response.status_code >= 400:
                        raise FetchError(f"{url} answered {response.status_code}")
                    data = bytearray()
                    async for chunk in response.aiter_bytes():
                        data += chunk
                        if len(data) > max_bytes:
                            raise FetchError(f"{url} is larger than {max_bytes:,} bytes")
                    return bytes(data)
            except httpx.HTTPError as exc:
                raise FetchError(f"couldn't download {url}: {exc}") from exc
        raise FetchError(f"{url} redirected more than {_MAX_REDIRECTS} times")
