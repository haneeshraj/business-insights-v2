"""Checking images, and cutting parts out of the screenshot, with Pillow."""

import io
import re
from dataclasses import dataclass
from typing import Final

from PIL import Image, UnidentifiedImageError

from bi2.core.models import Box

# An SVG file, after any XML declaration, comments or doctype.
_SVG: Final = re.compile(
    rb"^\s*(?:<\?xml[^>]*>\s*)?(?:<!--.*?-->\s*)*(?:<!DOCTYPE[^>]*>\s*)?<svg\b", re.S | re.I
)
_EXTENSIONS: Final = {
    "PNG": "png", "JPEG": "jpg", "GIF": "gif", "WEBP": "webp", "ICO": "ico", "BMP": "bmp",
    "AVIF": "avif",
}  # fmt: skip
_NOT_READABLE: Final = (
    UnidentifiedImageError, OSError, SyntaxError, ValueError, EOFError,
    Image.DecompressionBombError,
)  # fmt: skip


@dataclass(frozen=True)
class ImageInfo:
    """What a file turned out to be, judged by its content rather than its name."""

    extension: str  # "png", "jpg", "svg" and so on
    width: int  # 0 for an SVG, which has no fixed size
    height: int


def inspect_image(data: bytes) -> ImageInfo | None:
    """What kind of image the bytes are, and its size, or None when they aren't an image."""
    if _SVG.match(data[:4096].removeprefix(b"\xef\xbb\xbf")):
        return ImageInfo("svg", 0, 0)
    try:
        with Image.open(io.BytesIO(data)) as image:
            kind, (width, height) = image.format, image.size
            image.verify()  # reads the whole file, so a truncated or broken one is caught
    except _NOT_READABLE:
        return None
    extension = _EXTENSIONS.get(kind or "")
    return ImageInfo(extension, width, height) if extension else None


def logo_problem(info: ImageInfo | None) -> str | None:
    """Why an image can't be a logo, or None when it can."""
    if info is None:
        return "isn't an image"
    if info.extension == "svg":
        return None
    width, height = info.width, info.height
    if width <= 1 or height <= 1:
        return "is a one-pixel tracker or placeholder"
    if min(width, height) < 16:
        return f"is too small ({width}x{height})"
    if max(width, height) / min(width, height) > 12:
        return f"is a strip ({width}x{height}), not a logo"
    if info.extension == "jpg" and width * height > 1_500_000:
        return f"looks like a photo ({width}x{height})"
    return None


def crop(screenshot: bytes, box: Box) -> bytes | None:
    """The part of the screenshot an element was drawn in, as a PNG, or None when the element
    isn't on the screenshot. Both measure in the page's pixels."""
    left, top = round(box.x), round(box.y)
    right, bottom = round(box.x + box.width), round(box.y + box.height)
    try:
        with Image.open(io.BytesIO(screenshot)) as image:
            if right - left < 1 or bottom - top < 1 or left < 0 or top < 0:
                return None
            if right > image.width or bottom > image.height:
                return None
            out = io.BytesIO()
            image.crop((left, top, right, bottom)).save(out, format="PNG")
    except _NOT_READABLE:
        return None
    return out.getvalue()
