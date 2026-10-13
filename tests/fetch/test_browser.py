"""Tests for BrowserFetcher, against the local test website."""

import time
from collections.abc import AsyncIterator
from typing import get_args

import pytest

from bi2.core.errors import BrowserUnavailable, FetchError, PageTimeout, UnsafeUrl
from bi2.core.models import RenderedImage
from bi2.fetch.browser import BrowserFetcher, BrowserName
from bi2.fetch.http import HttpDownloader
from tests.conftest import LOGO_PNG

pytestmark = pytest.mark.browser

FULL_BROWSERS = ("chromium", "chrome", "edge")


@pytest.fixture
async def auto_fetcher() -> AsyncIterator[BrowserFetcher]:
    """A fetcher left to pick its browsers, so it falls back on a full one."""
    async with BrowserFetcher(timeout_s=10, allow_private=True) as fetcher:
        if fetcher.browser_name != "chromium-shell":
            pytest.skip("needs Playwright's Chromium shell, the browser that falls back")
        yield fetcher


def _image(images: tuple[RenderedImage, ...], alt: str) -> RenderedImage:
    return next(image for image in images if image.alt == alt)


async def test_captures_the_rendered_page_and_a_screenshot(
    fetcher: BrowserFetcher, site: str
) -> None:
    snapshot = await fetcher.fetch(f"{site}/cafe")
    assert snapshot.status_code == 200
    assert "12 Queen St W" in snapshot.html
    assert snapshot.screenshot is not None
    assert snapshot.screenshot[:2] == b"\xff\xd8"  # a JPEG


async def test_reads_the_visible_text_of_each_region(fetcher: BrowserFetcher, site: str) -> None:
    text = (await fetcher.fetch(f"{site}/cafe")).text
    assert text is not None
    assert text.header == "Menu"
    assert text.main == "Fresh coffee daily"  # the hidden paragraph is left out
    assert text.footer == "Example Cafe, 12 Queen St W, Toronto"


async def test_footers_drawn_only_when_seen_are_read(fetcher: BrowserFetcher, site: str) -> None:
    text = (await fetcher.fetch(f"{site}/lazy-footer")).text
    assert text is not None
    assert text.footer == "12 Queen St W, Toronto"


async def test_header_logo_knows_where_it_sits(fetcher: BrowserFetcher, site: str) -> None:
    logo = _image((await fetcher.fetch(f"{site}/cafe")).images, "Example Cafe logo")
    assert logo.url == f"{site}/images/logo.png"
    assert logo.in_header
    assert logo.links_home
    assert logo.box is not None
    assert (logo.box.width, logo.box.height) == (160, 60)


async def test_pages_that_scroll_smoothly_are_read_from_the_top(
    fetcher: BrowserFetcher, site: str
) -> None:
    logo = _image((await fetcher.fetch(f"{site}/smooth")).images, "Fixed logo")
    assert logo.box is not None
    assert logo.box.y < 50  # read with the page back at the top, not part of the way down
    assert logo.links_home  # /en/home.html is a home page too


async def test_a_languages_home_page_counts_as_home(fetcher: BrowserFetcher, site: str) -> None:
    footer_logo = _image((await fetcher.fetch(f"{site}/cafe")).images, "Footer logo")
    assert footer_logo.links_home  # it links to /en/


async def test_lazy_images_report_their_real_url(fetcher: BrowserFetcher, site: str) -> None:
    hero = _image((await fetcher.fetch(f"{site}/cafe")).images, "Our cafe")
    assert hero.url == f"{site}/images/hero.png"
    assert not hero.in_header


async def test_images_with_an_empty_source_dont_report_the_page_address(
    fetcher: BrowserFetcher, site: str
) -> None:
    images = (await fetcher.fetch(f"{site}/cafe")).images
    assert _image(images, "Late image").url == f"{site}/images/late.png"
    assert _image(images, "Image with no source").url == ""


async def test_inline_svg_logos_are_captured(fetcher: BrowserFetcher, site: str) -> None:
    wordmark = _image((await fetcher.fetch(f"{site}/cafe")).images, "Example Cafe wordmark")
    assert wordmark.kind == "svg"
    assert wordmark.url == ""


async def test_the_browser_keeps_copies_of_images_a_site_wont_give_out_again(
    fetcher: BrowserFetcher, site: str
) -> None:
    logo = f"{site}/images/browser-only.png"
    snapshot = await fetcher.fetch(f"{site}/browser-only-logo")
    assert snapshot.image_copies == {logo: LOGO_PNG}
    async with HttpDownloader(allow_private=True) as downloader:
        with pytest.raises(FetchError):  # the site refuses a separate download
            await downloader.download(logo, max_bytes=1_000_000)


async def test_an_svg_logo_keeps_its_own_code_with_the_page_styles_written_in(
    fetcher: BrowserFetcher, site: str
) -> None:
    images = (await fetcher.fetch(f"{site}/svg-logo")).images
    logo = _image(images, "Example Cafe")
    assert logo.kind == "svg"
    assert "fill:rgb(200, 30, 40)" in logo.svg  # from the stylesheet, which a file wouldn't have
    assert '<symbol id="cup"' in logo.svg  # the shape it borrows is copied in
    assert "<script" not in logo.svg
    assert "onload" not in logo.svg
    # A picture drawn inside an SVG is that picture's own file.
    picture = _image(images, "Example Cafe on a platform")
    assert (picture.kind, picture.url) == ("img", f"{site}/images/brand.png")


async def test_redirects_are_followed(fetcher: BrowserFetcher, site: str) -> None:
    snapshot = await fetcher.fetch(f"{site}/redirect")
    assert snapshot.url == f"{site}/redirect"
    assert snapshot.final_url == f"{site}/cafe"


async def test_bot_checks_are_given_time_to_pass(fetcher: BrowserFetcher, site: str) -> None:
    snapshot = await fetcher.fetch(f"{site}/check")
    assert snapshot.status_code == 200  # the real page's status, not the check's
    assert snapshot.final_url == f"{site}/cafe"
    assert "12 Queen St W" in snapshot.html


async def test_bot_checks_that_say_ok_are_still_waited_on(
    fetcher: BrowserFetcher, site: str
) -> None:
    snapshot = await fetcher.fetch(f"{site}/check-ok")
    assert snapshot.final_url == f"{site}/cafe"


async def test_a_bot_check_that_never_lets_us_through_is_a_refusal(
    browser: BrowserName, site: str
) -> None:
    async with BrowserFetcher(browser=browser, allow_private=True, bot_check_wait_s=1) as fetcher:
        with pytest.raises(FetchError, match="behind a bot check"):
            await fetcher.fetch(f"{site}/check-stuck")


async def test_error_pages_with_no_scripts_are_not_waited_on(
    fetcher: BrowserFetcher, site: str
) -> None:
    started = time.monotonic()
    snapshot = await fetcher.fetch(f"{site}/denied")
    assert snapshot.status_code == 403
    assert time.monotonic() - started < 8  # waiting for a bot check would take 10 s


async def test_pages_that_load_stay_in_the_shell(auto_fetcher: BrowserFetcher, site: str) -> None:
    snapshot = await auto_fetcher.fetch(f"{site}/cafe")
    assert snapshot.loaded_with == "chromium-shell"


async def test_refused_pages_load_again_in_a_full_browser(
    auto_fetcher: BrowserFetcher, site: str
) -> None:
    snapshot = await auto_fetcher.fetch(f"{site}/refused-once/auto")
    assert snapshot.status_code == 200
    assert snapshot.loaded_with in FULL_BROWSERS


async def test_dropped_connections_load_again_in_a_full_browser(
    auto_fetcher: BrowserFetcher, site: str
) -> None:
    snapshot = await auto_fetcher.fetch(f"{site}/dropped-once/auto")
    assert snapshot.status_code == 200
    assert snapshot.loaded_with in FULL_BROWSERS


async def test_pages_too_slow_for_the_shell_load_again_in_a_full_browser(site: str) -> None:
    async with BrowserFetcher(timeout_s=1, allow_private=True) as fetcher:
        if fetcher.browser_name != "chromium-shell":
            pytest.skip("needs Playwright's Chromium shell, the browser that falls back")
        snapshot = await fetcher.fetch(f"{site}/slow-once/auto")
    assert snapshot.status_code == 200
    assert snapshot.loaded_with in FULL_BROWSERS


async def test_a_page_too_slow_for_every_browser_still_times_out(site: str) -> None:
    async with BrowserFetcher(timeout_s=1, allow_private=True) as fetcher:
        with pytest.raises(PageTimeout, match="didn't load within 1 seconds"):
            await fetcher.fetch(f"{site}/slow")


async def test_a_chosen_browser_is_never_swapped(
    fetcher: BrowserFetcher, browser: BrowserName, site: str
) -> None:
    snapshot = await fetcher.fetch(f"{site}/refused-once/chosen")
    assert snapshot.status_code == 403
    assert snapshot.loaded_with == browser


async def test_slow_pages_time_out(browser: BrowserName, site: str) -> None:
    async with BrowserFetcher(timeout_s=1, browser=browser, allow_private=True) as fetcher:
        with pytest.raises(PageTimeout, match="didn't load within 1 seconds"):
            await fetcher.fetch(f"{site}/slow")


async def test_private_addresses_are_refused_by_default(browser: BrowserName, site: str) -> None:
    async with BrowserFetcher(browser=browser) as fetcher:
        with pytest.raises(UnsafeUrl, match="isn't on the public internet"):
            await fetcher.fetch(f"{site}/cafe")


@pytest.mark.parametrize("name", get_args(BrowserName))
async def test_each_browser_can_load_pages(name: BrowserName, site: str) -> None:
    try:
        async with BrowserFetcher(browser=name, allow_private=True) as fetcher:
            snapshot = await fetcher.fetch(f"{site}/cafe")
    except BrowserUnavailable:
        pytest.skip(f"{name} isn't installed on this machine")
    assert fetcher.browser_name == snapshot.loaded_with == name
    assert "12 Queen St W" in snapshot.html
