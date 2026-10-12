"""Tests for checking images and cutting them out of the screenshot."""

import pytest

from bi2.core.models import Box
from bi2.resolvers.images import ImageInfo, crop, inspect_image, logo_problem
from tests.resolvers.images import SVG, picture, screenshot_with_logo


def test_images_are_known_by_their_content() -> None:
    assert inspect_image(picture(120, 40)) == ImageInfo("png", 120, 40)
    assert inspect_image(picture(64, 64, "JPEG")) == ImageInfo("jpg", 64, 64)
    assert inspect_image(SVG) == ImageInfo("svg", 0, 0)
    assert inspect_image(b"<html><body>Not found</body></html>") is None
    assert inspect_image(picture(120, 40)[:60]) is None  # cut off partway


@pytest.mark.parametrize(
    ("info", "problem"),
    [
        (ImageInfo("png", 120, 40), None),
        (ImageInfo("svg", 0, 0), None),
        (ImageInfo("gif", 1, 1), "is a one-pixel tracker or placeholder"),
        (ImageInfo("png", 12, 12), "is too small (12x12)"),
        (ImageInfo("png", 2000, 50), "is a strip (2000x50), not a logo"),
        (ImageInfo("jpg", 2000, 1000), "looks like a photo (2000x1000)"),
        (None, "isn't an image"),
    ],
)
def test_what_rules_an_image_out_as_a_logo(info: ImageInfo | None, problem: str | None) -> None:
    assert logo_problem(info) == problem


def test_an_element_is_cut_out_of_the_screenshot() -> None:
    screenshot = screenshot_with_logo(20, 10, 160, 60)
    cut = crop(screenshot, Box(x=20, y=10, width=160, height=60))
    assert cut is not None
    assert inspect_image(cut) == ImageInfo("png", 160, 60)
    assert crop(screenshot, Box(x=20, y=900, width=160, height=60)) is None  # below the screen
