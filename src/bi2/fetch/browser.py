"""Loading pages in a real browser, which captures most of a page's evidence."""

import contextlib
from datetime import UTC, datetime
from types import TracebackType
from typing import Literal, Self
from urllib.parse import urlsplit

from playwright.async_api import Browser, Playwright, Route, ViewportSize, async_playwright
from playwright.async_api import Error as PlaywrightError
from playwright.async_api import TimeoutError as PlaywrightTimeoutError
from pydantic import ValidationError

from bi2 import __version__
from bi2.core.errors import BrowserUnavailable, FetchError, PageTimeout, UnsafeUrl
from bi2.core.models import PageSnapshot, RenderedImage
from bi2.fetch.safety import Resolver, ensure_public_url, host_is_public, system_resolver

# "chromium" is Playwright's own browser; "chrome" is Google Chrome installed on this machine.
BrowserName = Literal["chromium", "chrome"]
BrowserChoice = Literal["auto", "chromium", "chrome"]

# Runs in the page. Lists every image-like element with where it was drawn, whether it sits in
# the header, and whether it links to the home page. Lazy-loaded images report their real URL
# instead of the placeholder.
_IMAGES_SCRIPT = """
() => {
  const absolute = (value) => { try { return new URL(value, location.href).href; } catch { return ""; } };
  const linksHome = (el) => {
    const link = el.closest("a[href]");
    if (!link) return false;
    try {
      const target = new URL(link.href, location.href);
      return target.origin === location.origin && (target.pathname === "/" || target.pathname === "");
    } catch { return false; }
  };
  const inHeader = (el) => !!el.closest("header, nav, [role=banner], [class*=header i], [id*=header i]");
  const box = (el) => {
    const r = el.getBoundingClientRect();
    return { x: r.x + window.scrollX, y: r.y + window.scrollY, width: r.width, height: r.height };
  };
  const describe = (el, kind, url, alt) => ({
    kind, url, alt: alt || "", css_class: String(el.getAttribute("class") || ""),
    element_id: el.id || "", box: box(el), in_header: inHeader(el), links_home: linksHome(el),
  });
  const found = [];
  for (const img of document.images) {
    let url = img.currentSrc || img.src || "";
    if (url === location.href) url = "";  // an empty src makes the browser report the page itself
    if (!url || url.startsWith("data:")) {
      const lazy = img.dataset.src || img.dataset.lazySrc || img.getAttribute("data-original");
      if (lazy) url = absolute(lazy);
    }
    found.push(describe(img, "img", url, img.alt));
  }
  for (const svg of document.querySelectorAll("svg")) {
    const r = svg.getBoundingClientRect();
    if (r.width < 24 || r.height < 12) continue;  // icons, not logos
    const title = svg.querySelector("title");
    found.push(describe(svg, "svg", "", svg.getAttribute("aria-label") || (title ? title.textContent : "")));
  }
  for (const el of document.querySelectorAll("header *, nav *, [class*=logo i]")) {
    const match = getComputedStyle(el).backgroundImage.match(/url\\(["']?(.*?)["']?\\)/);
    if (match) found.push(describe(el, "background", absolute(match[1]), el.getAttribute("aria-label")));
  }
  return found.slice(0, 200);
}
"""


class BrowserFetcher:
    """Loads pages in headless Chromium: the rendered HTML, every image with its position, and
    a screenshot of the first screen.

    Every request a page makes, including redirects and images, is checked before it's sent,
    so a page can't make v2 fetch from a private network.
    """

    def __init__(
        self,
        *,
        timeout_s: float = 20.0,
        viewport: tuple[int, int] = (1280, 800),
        browser: BrowserChoice = "auto",  # "auto" tries Chromium, then Chrome
        allow_private: bool = False,  # only for tests that serve pages from this machine
        resolver: Resolver = system_resolver,
    ) -> None:
        self._timeout_ms = timeout_s * 1000
        self._viewport: ViewportSize = {"width": viewport[0], "height": viewport[1]}
        self._choice = browser
        self._allow_private = allow_private
        self._resolver = resolver
        self._public_hosts: dict[str, bool] = {}
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self.browser_name: BrowserName | None = None  # which browser started

    async def __aenter__(self) -> Self:
        names: tuple[BrowserName, ...]
        if self._choice == "chromium":
            names = ("chromium",)
        elif self._choice == "chrome":
            names = ("chrome",)
        else:
            names = ("chromium", "chrome")
        self._playwright = await async_playwright().start()
        for name in names:
            try:
                self._browser = await self._playwright.chromium.launch(
                    channel="chrome" if name == "chrome" else None
                )
            except PlaywrightError:
                continue
            self.browser_name = name
            return self
        await self._playwright.stop()
        raise BrowserUnavailable(
            "no browser could start. Run `uv run playwright install chromium`, "
            "or install Google Chrome."
        )

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()

    async def _is_public(self, host: str) -> bool:
        if host not in self._public_hosts:
            self._public_hosts[host] = await host_is_public(host, self._resolver)
        return self._public_hosts[host]

    def _user_agent(self, browser: Browser) -> str:
        major = browser.version.split(".")[0]
        return (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
            f"Chrome/{major}.0.0.0 Safari/537.36 bi2/{__version__}"
        )

    async def fetch(self, url: str) -> PageSnapshot:
        """Load one page. Raises UnsafeUrl, PageTimeout or FetchError."""
        if self._browser is None:
            raise RuntimeError("use BrowserFetcher inside an `async with` block")
        if not self._allow_private:
            await ensure_public_url(url, self._resolver)

        blocked: list[str] = []

        async def guard(route: Route) -> None:
            parts = urlsplit(route.request.url)
            if (
                self._allow_private
                or parts.scheme in ("data", "blob")
                or await self._is_public(parts.hostname or "")
            ):
                await route.continue_()
            else:
                blocked.append(route.request.url)
                await route.abort("blockedbyclient")

        context = await self._browser.new_context(
            viewport=self._viewport,
            user_agent=self._user_agent(self._browser),
            service_workers="block",
        )
        try:
            page = await context.new_page()
            await page.route("**/*", guard)
            try:
                response = await page.goto(
                    url, wait_until="domcontentloaded", timeout=self._timeout_ms
                )
            except PlaywrightTimeoutError as exc:
                raise PageTimeout(
                    f"{url} didn't load within {self._timeout_ms / 1000:g} seconds"
                ) from exc
            # Give images and late scripts a moment, without waiting forever for busy pages.
            with contextlib.suppress(PlaywrightTimeoutError):
                await page.wait_for_load_state("load", timeout=5_000)
            with contextlib.suppress(PlaywrightTimeoutError):
                await page.wait_for_load_state("networkidle", timeout=2_000)
            images = await page.evaluate(_IMAGES_SCRIPT)
            return PageSnapshot(
                url=url,
                final_url=page.url,
                status_code=response.status if response else None,
                html=await page.content(),
                images=tuple(RenderedImage.model_validate(image) for image in images),
                screenshot=await page.screenshot(type="jpeg", quality=70),
                fetched_at=datetime.now(UTC),
            )
        except PlaywrightError as exc:
            if blocked:
                raise UnsafeUrl(f"{url} tried to reach a private address: {blocked[0]}") from exc
            raise FetchError(f"couldn't load {url}: {exc.message}") from exc
        except ValidationError as exc:  # for example, the page ended up on a non-web address
            raise FetchError(f"couldn't use what {url} returned: {exc}") from exc
        finally:
            await context.close()
