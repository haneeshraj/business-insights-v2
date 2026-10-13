"""Setup shared by all tests: a tiny local website, and a browser to load it with."""

import asyncio
import base64
import contextlib
import io
import threading
import time
from collections.abc import AsyncIterator, Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from PIL import Image

from bi2.core.errors import BrowserUnavailable
from bi2.fetch.browser import BrowserFetcher, BrowserName

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
    <p>Fresh coffee daily</p>
    <p style="display: none">Staff only</p>
    <img src="data:image/gif;base64,R0lGODlhAQABAAAAACH5BAEKAAEALAAAAAABAAEAAAICTAEAOw=="
         data-src="/images/hero.png" alt="Our cafe" width="600" height="300">
    <svg width="120" height="40" aria-label="Example Cafe wordmark"><rect width="120" height="40"/></svg>
    <img src="" data-src="/images/late.png" alt="Late image" width="80" height="80">
    <img src="" alt="Image with no source" width="80" height="80">
  </main>
  <footer>Example Cafe, 12 Queen St W, Toronto
    <a href="/en/"><img src="/images/footer-logo.png" alt="Footer logo" width="80" height="30"></a>
  </footer>
</body>
</html>"""

# A bot check like Cloudflare's: an error page whose script moves on to the real page.
CHECK_PAGE = b"""<!doctype html>
<html><head><title>Just a moment...</title></head>
<body><script>setTimeout(() => location.replace("/cafe"), 1000)</script></body></html>"""

# A tall page that shows its footer's text only while the footer is in view.
LAZY_FOOTER_PAGE = b"""<!doctype html>
<html><body>
<main style="height: 3000px">A tall page</main>
<footer id="footer" style="min-height: 50px"></footer>
<script>
  const footer = document.getElementById("footer");
  new IntersectionObserver((seen) => {
    footer.textContent = seen[0].isIntersecting ? "12 Queen St W, Toronto" : "";
  }).observe(footer);
</script>
</body></html>"""

# A long page that scrolls smoothly, with its logo in a header fixed to the top of the screen.
SMOOTH_PAGE = b"""<!doctype html>
<html style="scroll-behavior: smooth"><body style="margin: 0">
<header style="position: fixed; top: 0; width: 100%">
  <a href="/en/home.html"><img src="/images/logo.png" alt="Fixed logo" width="100" height="40"></a>
</header>
<main style="height: 4000px; padding-top: 60px">A long page</main>
<footer>Bottom</footer>
</body></html>"""

# Bot checks like Akamai's that say "200 OK": one moves on to the real page, one never does.
PASSING_CHECK_PAGE = b"""<!doctype html>
<html><body><div id="sec-if-cpt-container">Checking your browser</div>
<script>setTimeout(() => location.replace("/cafe"), 1000)</script></body></html>"""
STUCK_CHECK_PAGE = b"""<!doctype html>
<html><body><div id="sec-if-cpt-container">Press and hold</div></body></html>"""

# A block like Akamai's: an error page with no scripts, so nothing will move it on.
DENIED_PAGE = b"<html><head><title>Access Denied</title></head><body>Access Denied</body></html>"

# A page whose logo is given only to browsers, like sites that refuse separate downloads.
BROWSER_ONLY_PAGE = b"""<!doctype html>
<html><head><title>Example Cafe</title></head>
<body><header><a href="/"><img src="/images/browser-only.png" alt="Example Cafe" width="160"
height="60"></a></header><main>Coffee</main></body></html>"""

# A 1x1 transparent PNG.
PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
)


def _logo_png() -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (160, 60), "blue").save(out, format="PNG")
    return out.getvalue()


# A logo-sized PNG, for tests that check a downloaded logo.
LOGO_PNG = _logo_png()

_visited: set[str] = set()
_visited_lock = threading.Lock()


def _first_visit(path: str) -> bool:
    """True the first time a page is asked for, for the pages that only misbehave once."""
    with _visited_lock:
        first = path not in _visited
        _visited.add(path)
    return first


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        path = self.path
        if path.startswith("/dropped-once/") and _first_visit(path):
            return  # hang up without answering, like some sites do to bots
        if path.startswith("/refused-once/") and _first_visit(path):
            path = "/denied"
        if path == "/redirect":
            self.send_response(302)
            self.send_header("Location", "/cafe")
            self.end_headers()
            return
        if path == "/slow":
            time.sleep(3)
        if path in ("/cafe", "/slow") or path.startswith(("/refused-once/", "/dropped-once/")):
            self._send(200, "text/html", CAFE_PAGE)
        elif path == "/lazy-footer":
            self._send(200, "text/html", LAZY_FOOTER_PAGE)
        elif path == "/smooth":
            self._send(200, "text/html", SMOOTH_PAGE)
        elif path == "/check":
            self._send(403, "text/html", CHECK_PAGE)
        elif path == "/check-ok":
            self._send(200, "text/html", PASSING_CHECK_PAGE)
        elif path == "/check-stuck":
            self._send(200, "text/html", STUCK_CHECK_PAGE)
        elif path == "/denied":
            self._send(403, "text/html", DENIED_PAGE)
        elif path == "/browser-only-logo":
            self._send(200, "text/html", BROWSER_ONLY_PAGE)
        elif path == "/images/browser-only.png":
            # A browser says what it wants an image for; a separate download doesn't.
            if self.headers.get("Sec-Fetch-Dest") == "image":
                self._send(200, "image/png", LOGO_PNG)
            else:
                self._send(403, "text/plain", b"forbidden")
        elif path == "/images/brand.png":
            self._send(200, "image/png", LOGO_PNG)
        elif path.startswith("/images/"):
            self._send(200, "image/png", PNG)
        else:
            self._send(404, "text/plain", b"not found")

    def _send(self, status: int, content_type: str, body: bytes) -> None:
        # Browsers hang up early when a page moves on, so a dropped connection is normal here.
        with contextlib.suppress(ConnectionError):
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


async def _browser_that_starts() -> BrowserName | None:
    async with BrowserFetcher() as fetcher:
        return fetcher.browser_name


@pytest.fixture(scope="session")
def browser() -> BrowserName:
    """The browser the tests use: the first of Playwright's Chromium (the shell, then the full
    build), Chrome and Edge that starts."""
    try:
        name = asyncio.run(_browser_that_starts())
    except BrowserUnavailable:
        pytest.skip("no browser available; run `uv run playwright install chromium`")
    assert name is not None
    return name


@pytest.fixture
async def fetcher(browser: BrowserName) -> AsyncIterator[BrowserFetcher]:
    """A fetcher allowed to load the local test website, which is on a private address."""
    async with BrowserFetcher(timeout_s=10, browser=browser, allow_private=True) as fetcher:
        yield fetcher
