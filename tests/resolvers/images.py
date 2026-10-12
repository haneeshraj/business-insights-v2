"""Small real images for tests, made with Pillow."""

import io

from PIL import Image


def picture(width: int, height: int, kind: str = "PNG", color: str = "red") -> bytes:
    """An image of one color in the given format."""
    out = io.BytesIO()
    Image.new("RGB", (width, height), color).save(out, format=kind)
    return out.getvalue()


def screenshot_with_logo(left: int, top: int, width: int, height: int) -> bytes:
    """A 1280x800 white screenshot with a blue logo-sized block drawn at the given spot."""
    image = Image.new("RGB", (1280, 800), "white")
    image.paste(Image.new("RGB", (width, height), "blue"), (left, top))
    out = io.BytesIO()
    image.save(out, format="JPEG", quality=90)
    return out.getvalue()


SVG = b'<?xml version="1.0"?>\n<svg xmlns="http://www.w3.org/2000/svg" width="120" height="40"/>'
