"""Loading pages in a real browser, which captures most of a page's evidence."""

import asyncio
import contextlib
from datetime import UTC, datetime
from types import TracebackType
from typing import Any, Literal, NamedTuple, Self
from urllib.parse import urlsplit

from playwright.async_api import Browser, Page, Playwright, Route, ViewportSize, async_playwright
from playwright.async_api import Error as PlaywrightError
from playwright.async_api import TimeoutError as PlaywrightTimeoutError
from pydantic import ValidationError

from bi2 import __version__
from bi2.core.errors import BrowserUnavailable, FetchError, PageTimeout, UnsafeUrl
from bi2.core.models import PageSnapshot, RenderedImage, TextRegions
from bi2.fetch import page_scripts
from bi2.fetch.safety import Resolver, ensure_public_url, host_is_public, system_resolver

# Playwright's Chromium comes in two builds: "chromium-shell", stripped down for headless use,
# and "chromium", the full browser. The shell is about 40% faster, but sites that block bots
# spot it more easily. "chrome" and "edge" are Google Chrome and Microsoft Edge installed on
# this machine; they're full browsers too.
BrowserName = Literal["chromium-shell", "chromium", "chrome", "edge"]
BrowserChoice = Literal["auto", BrowserName]

# The Playwright channel that starts each browser.
_CHANNELS: dict[BrowserName, str | None] = {
    "chromium-shell": None,
    "chromium": "chromium",
    "chrome": "chrome",
    "edge": "msedge",
}

# "auto" loads pages in the shell. Pages a site refuses it are loaded again in the first of these
# full browsers that starts. Playwright's own build comes first because it's the version
# Playwright is tested against.
_FULL_BROWSERS: tuple[BrowserName, ...] = ("chromium", "chrome", "edge")
_AUTO_ORDER: tuple[BrowserName, ...] = ("chromium-shell", *_FULL_BROWSERS)

# How many times to try reading a page that keeps moving on to other pages while it's read.
_READ_ATTEMPTS = 3


class _Started(NamedTuple):
    """A browser that's running, and which one it is."""

    name: BrowserName
    browser: Browser


async def _start_first(playwright: Playwright, names: tuple[BrowserName, ...]) -> _Started | None:
    """Start the first of these browsers that's installed."""
    for name in names:
        try:
            return _Started(name, await playwright.chromium.launch(channel=_CHANNELS[name]))
        except PlaywrightError:
            continue
    return None


async def _wait_for_bot_check(page: Page, wait_ms: float) -> None:
    """If a bot check is running in the page, give it time to pass and let the real page load."""
    with contextlib.suppress(PlaywrightError):  # if it can't be told, read the page as it is
        if await page.evaluate(page_scripts.NO_BOT_CHECK_RUNNING):
            return
        await page.wait_for_function(
            page_scripts.NO_BOT_CHECK_RUNNING, polling=250, timeout=wait_ms
        )
        await page.wait_for_load_state("load", timeout=5_000)


async def _scroll_through(page: Page) -> dict[str, Any] | None:
    """Scroll to the bottom and back, so parts drawn only when seen get drawn. Returns the text
    the page showed at the bottom, since some footers hide again once they're out of view."""
    with contextlib.suppress(PlaywrightError):  # a page that moves on meanwhile is read anyway
        seen: dict[str, Any] | None = await page.evaluate(page_scripts.SCROLL)
        return seen
    return None


def _longer(a: TextRegions, b: TextRegions) -> TextRegions:
    """Each region's text from whichever of two readings showed more of it."""
    return TextRegions(
        header=max(a.header, b.header, key=len),
        main=max(a.main, b.main, key=len),
        footer=max(a.footer, b.footer, key=len),
    )


async def _read(page: Page, url: str) -> tuple[dict[str, Any], bytes]:
    """Read the page and take its screenshot, both from the same page. If the page moves on to
    another page meanwhile, that one is read once it has loaded."""
    for attempt in range(1, _READ_ATTEMPTS + 1):
        try:
            read: dict[str, Any] = await page.evaluate(page_scripts.READ)
            screenshot = await page.screenshot(type="jpeg", quality=70)
            if await page.evaluate(page_scripts.PAGE_ID) == read["page"]:
                return read, screenshot
        except PlaywrightTimeoutError:
            raise  # a slow page won't be quicker the second time
        except PlaywrightError:  # the page moved on in the middle of a step
            if attempt == _READ_ATTEMPTS:
                raise
        with contextlib.suppress(PlaywrightTimeoutError):
            await page.wait_for_load_state("load", timeout=5_000)
    raise FetchError(f"{url} kept moving on to other pages while it was read")


class BrowserFetcher:
    """Loads pages in a headless browser: the rendered HTML, every image with its position, and
    a screenshot of the first screen.

    With "auto", pages load in the fast Chromium shell, and a page the site won't give the shell
    is loaded again in a full browser.

    Every request a page makes, including redirects and images, is checked before it's sent,
    so a page can't make v2 fetch from a private network.
    """

    def __init__(
        self,
        *,
        timeout_s: float = 20.0,
        viewport: tuple[int, int] = (1280, 800),
        browser: BrowserChoice = "auto",
        allow_private: bool = False,  # only for tests that serve pages from this machine
        resolver: Resolver = system_resolver,
        bot_check_wait_s: float = 10.0,  # how long a bot check in the page gets to pass
    ) -> None:
        self._timeout_ms = timeout_s * 1000
        self._bot_check_wait_ms = bot_check_wait_s * 1000
        self._viewport: ViewportSize = {"width": viewport[0], "height": viewport[1]}
        self._choice = browser
        self._allow_private = allow_private
        self._resolver = resolver
        self._public_hosts: dict[str, bool] = {}
        self._playwright: Playwright | None = None
        self._main: _Started | None = None  # where pages load first
        self._full: _Started | None = None  # where refused pages load again
        self._full_wanted = False  # true until the full browser has been started, if it's needed
        self._full_lock = asyncio.Lock()

    @property
    def browser_name(self) -> BrowserName | None:
        """The browser pages load in first, once it has started."""
        return self._main.name if self._main else None

    async def __aenter__(self) -> Self:
        names = _AUTO_ORDER if self._choice == "auto" else (self._choice,)
        self._playwright = await async_playwright().start()
        self._main = await _start_first(self._playwright, names)
        if self._main is None:
            await self._playwright.stop()
            raise BrowserUnavailable(
                f"no browser could start (tried {', '.join(names)}). Run "
                "`uv run playwright install chromium`, or install Google Chrome or Microsoft Edge."
            )
        # Only the shell needs a full browser to fall back on, and only when no browser was chosen.
        self._full_wanted = self._choice == "auto" and self._main.name == "chromium-shell"
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        for started in (self._main, self._full):
            if started:
                await started.browser.close()
        if self._playwright:
            await self._playwright.stop()

    async def _full_browser(self) -> _Started | None:
        """The full browser that refused pages are loaded again in, started the first time it's
        needed. None when there isn't one."""
        async with self._full_lock:  # pages loading at the same time start only one
            if self._full_wanted and self._playwright:
                self._full_wanted = False
                self._full = await _start_first(self._playwright, _FULL_BROWSERS)
        return self._full

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
        """Load one page. Raises UnsafeUrl, PageTimeout or FetchError.

        With "auto", a page the site won't give the shell (an error status or a dropped
        connection) is loaded again in a full browser.
        """
        if self._main is None:
            raise RuntimeError("use BrowserFetcher inside an `async with` block")
        if not self._allow_private:
            await ensure_public_url(url, self._resolver)
        try:
            snapshot = await self._load(self._main, url)
        except (PageTimeout, UnsafeUrl):
            raise  # a full browser wouldn't do better
        except FetchError:
            full = await self._full_browser()
            if full is None:
                raise
            return await self._load(full, url)
        if snapshot.status_code is not None and snapshot.status_code >= 400:
            full = await self._full_browser()
            if full is not None:
                return await self._load(full, url)
        return snapshot

    async def _load(self, started: _Started, url: str) -> PageSnapshot:
        """Load one page in one browser."""
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

        context = await started.browser.new_context(
            viewport=self._viewport,
            user_agent=self._user_agent(started.browser),
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
            await _wait_for_bot_check(page, self._bot_check_wait_ms)
            at_bottom = await _scroll_through(page)
            read, screenshot = await _read(page, url)
            if read["challenge"]:
                raise FetchError(f"{url} is behind a bot check that didn't let the browser through")
            text = TextRegions.model_validate(read["text"])
            if at_bottom and at_bottom["page"] == read["page"]:  # the same page, both times
                text = _longer(text, TextRegions.model_validate(at_bottom["text"]))
            return PageSnapshot(
                url=url,
                final_url=read["url"],
                # The page that was read, which a bot check may have moved on to.
                status_code=read["status"] or (response.status if response else None),
                html=read["html"],
                images=tuple(RenderedImage.model_validate(image) for image in read["images"]),
                text=text,
                screenshot=screenshot,
                fetched_at=datetime.now(UTC),
                loaded_with=started.name,
            )
        except PlaywrightError as exc:
            if blocked:
                raise UnsafeUrl(f"{url} tried to reach a private address: {blocked[0]}") from exc
            raise FetchError(f"couldn't load {url}: {exc.message}") from exc
        except ValidationError as exc:  # for example, the page ended up on a non-web address
            raise FetchError(f"couldn't use what {url} returned: {exc}") from exc
        finally:
            await context.close()
