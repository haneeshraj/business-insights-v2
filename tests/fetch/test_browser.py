"""Tests for BrowserFetcher, against the local test website."""

from typing import get_args

import pytest

from bi2.core.errors import BrowserUnavailable, PageTimeout, UnsafeUrl
from bi2.core.models import RenderedImage
from bi2.fetch.browser import BrowserFetcher, BrowserName

pytestmark = pytest.mark.browser


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


async def test_header_logo_knows_where_it_sits(fetcher: BrowserFetcher, site: str) -> None:
    logo = _image((await fetcher.fetch(f"{site}/cafe")).images, "Example Cafe logo")
    assert logo.url == f"{site}/images/logo.png"
    assert logo.in_header
    assert logo.links_home
    assert logo.box is not None
    assert (logo.box.width, logo.box.height) == (160, 60)


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


async def test_redirects_are_followed(fetcher: BrowserFetcher, site: str) -> None:
    snapshot = await fetcher.fetch(f"{site}/redirect")
    assert snapshot.url == f"{site}/redirect"
    assert snapshot.final_url == f"{site}/cafe"


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
    assert fetcher.browser_name == name
    assert "12 Queen St W" in snapshot.html
