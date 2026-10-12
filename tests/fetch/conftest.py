"""Shared setup for the fetch tests: a tiny local website, and a browser to load it with."""

import asyncio
import base64
import threading
import time
from collections.abc import AsyncIterator, Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from playwright.async_api import Error as PlaywrightError

from bi2.fetch.browser import BrowserFetcher

# A fake cafe homepage with the cases page loading has to handle: a header logo that links
# home, a lazy-loaded image showing a blank placeholder, and an inline SVG logo with no URL.
CAFE_PAGE = b"""<!doctype html>
<html>
<head><title>Example Cafe</title></head>
<body>
  <header>
    <a href="/"><img src="/images/logo.png" alt="Example Cafe logo" width="160" height="60"></a>
    <nav><a href="/menu">Menu</a></nav>
  </header>
  <main>
    <img src="data:image/gif;base64,R0lGODlhAQABAAAAACH5BAEKAAEALAAAAAABAAEAAAICTAEAOw=="
         data-src="/images/hero.png" alt="Our cafe" width="600" height="300">
    <svg width="120" height="40" aria-label="Example Cafe wordmark"><rect width="120" height="40"/></svg>
  </main>
  <footer>Example Cafe, 12 Queen St W, Toronto</footer>
</body>
</html>"""

# A 1x1 transparent PNG.
PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
)


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path == "/redirect":
            self.send_response(302)
            self.send_header("Location", "/cafe")
            self.end_headers()
            return
        if self.path == "/slow":
            time.sleep(3)
        if self.path in ("/cafe", "/slow"):
            self._send(200, "text/html", CAFE_PAGE)
        elif self.path.startswith("/images/"):
            self._send(200, "image/png", PNG)
        else:
            self._send(404, "text/plain", b"not found")

    def _send(self, status: int, content_type: str, body: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:  # keep test output quiet
        pass


@pytest.fixture(scope="session")
def site() -> Iterator[str]:
    """The base URL of the local test website."""
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


async def _launches(channel: str | None) -> None:
    async with BrowserFetcher(channel=channel):
        pass


@pytest.fixture(scope="session")
def browser_channel() -> str | None:
    """The first browser that starts: Playwright's own Chromium, then an installed Chrome."""
    for channel in (None, "chrome"):
        try:
            asyncio.run(_launches(channel))
        except PlaywrightError:
            continue
        return channel
    pytest.skip("no browser available; run `uv run playwright install chromium`")


@pytest.fixture
async def fetcher(browser_channel: str | None) -> AsyncIterator[BrowserFetcher]:
    """A fetcher allowed to load the local test website, which is on a private address."""
    async with BrowserFetcher(timeout_s=10, channel=browser_channel, allow_private=True) as fetcher:
        yield fetcher
