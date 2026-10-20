"""Checking images, and cutting parts out of the screenshot, with Pillow."""

import io
import re
from dataclasses import dataclass
from typing import Final

from PIL import Image, ImageDraw, ImageFont, UnidentifiedImageError

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


def logo_problem(info: ImageInfo | None, *, declared: bool = False) -> str | None:
    """Why an image can't be a logo, or None when it can. A file the business itself names
    as its logo isn't ruled out for being as big as a photo."""
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
    if info.extension == "jpg" and width * height > 1_500_000 and not declared:
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


# Colors that stand out on most pages, one per box in turn, so neighboring boxes differ.
_MARKS: Final = ("#e6007e", "#0057ff", "#00a86b", "#ff6a00", "#7a00e6", "#d40000")


def _overlap(a: tuple[float, ...], b: tuple[float, ...]) -> float:
    """How much of the smaller of two rectangles (left, top, right, bottom) the other covers."""
    width = min(a[2], b[2]) - max(a[0], b[0])
    height = min(a[3], b[3]) - max(a[1], b[1])
    if width <= 0 or height <= 0:
        return 0.0
    smaller = min((a[2] - a[0]) * (a[3] - a[1]), (b[2] - b[0]) * (b[3] - b[1]))
    return width * height / smaller if smaller > 0 else 0.0


def number_boxes(screenshot: bytes, boxes: list[tuple[int, Box]]) -> tuple[bytes, list[int]]:
    """The screenshot with each box outlined and labeled with its number, as a JPEG, and the
    numbers drawn: a box that isn't on the screenshot is left out. A model shown it can answer
    "which number is the logo?"."""

    with Image.open(io.BytesIO(screenshot)) as opened:
        image = opened.convert("RGB")
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default(size=18)
    drawn: list[int] = []
    outlined: list[tuple[int, int, int, int]] = []
    labels: list[tuple[float, float, float, float]] = []
    for number, box in boxes:
        left, top = round(box.x), round(box.y)
        right, bottom = round(box.x + box.width), round(box.y + box.height)
        if right - left < 4 or bottom - top < 4 or top >= image.height or left >= image.width:
            continue  # too small to see, or off the screenshot
        if any(_overlap((left, top, right, bottom), other) > 0.8 for other in outlined):
            continue  # drawn in the same place as a likelier candidate, so it's the same image
        color = _MARKS[len(drawn) % len(_MARKS)]
        draw.rectangle((left - 2, top - 2, right + 2, bottom + 2), outline=color, width=3)
        label = str(number)
        width = draw.textlength(label, font=font) + 10
        spots = [(left - 2, top - 26), (left + 2, top + 2), (right - width, top - 26),
                 (right - width - 2, top + 2), (left - 2, bottom + 4)]  # fmt: skip
        for x, y in spots:
            spot = (max(0.0, x), max(0.0, y), max(0.0, x) + width, max(0.0, y) + 24)
            if not any(_overlap(spot, other) > 0 for other in labels):
                break
        labels.append(spot)
        outlined.append((left, top, right, bottom))
        draw.rectangle(spot, fill=color)
        draw.text((spot[0] + 5, spot[1] + 2), label, fill="white", font=font)
        drawn.append(number)
    out = io.BytesIO()
    image.save(out, format="JPEG", quality=85)
    return out.getvalue(), drawn


_HEX: Final = re.compile(rb"#([0-9a-fA-F]{6}|[0-9a-fA-F]{3})\b")
_MOST_COLORS: Final = 4


def _plain_hex(code: str) -> str:
    code = code.lower()
    return "#" + ("".join(ch * 2 for ch in code) if len(code) == 3 else code)


def _is_background(red: int, green: int, blue: int) -> bool:
    """Near white or near black, which is usually what a logo sits on."""
    return min(red, green, blue) > 240 or max(red, green, blue) < 12


def brand_colors(data: bytes) -> tuple[str, ...]:
    """A logo's main colors, as "#rrggbb", the most used first. An SVG's are the colors its
    code fills and strokes with; a picture's come from its pixels, leaving out transparent,
    near-white and near-black ones."""
    if _SVG.match(data):
        found = [_plain_hex(match.decode()) for match in _HEX.findall(data)]
        counted: dict[str, int] = {}
        for color in found:
            red, green, blue = (int(color[i : i + 2], 16) for i in (1, 3, 5))
            if not _is_background(red, green, blue):
                counted[color] = counted.get(color, 0) + 1
        return tuple(sorted(counted, key=lambda c: -counted[c])[:_MOST_COLORS])
    try:
        with Image.open(io.BytesIO(data)) as opened:
            picture = opened.convert("RGBA")
    except _NOT_READABLE:
        return ()
    picture.thumbnail((96, 96))
    raw = picture.tobytes()
    shown = [(raw[i], raw[i + 1], raw[i + 2]) for i in range(0, len(raw), 4) if raw[i + 3] > 128]
    # A logo drawn all in white or black, like one made for a dark header, keeps that color.
    pixels = [p for p in shown if not _is_background(*p)] or shown
    if not pixels:
        return ()
    solid = Image.new("RGB", (len(pixels), 1))
    solid.frombytes(bytes(value for pixel in pixels for value in pixel))
    palette = solid.quantize(colors=8, method=Image.Quantize.MEDIANCUT)
    rgb = palette.getpalette() or []
    merged: list[tuple[int, tuple[int, int, int]]] = []
    for share, index in sorted(palette.getcolors() or [], reverse=True):
        at = int(index) * 3  # type: ignore[call-overload]
        shade = (rgb[at], rgb[at + 1], rgb[at + 2])
        # Shades a few steps apart are one color, the way anti-aliased edges are.
        near = next((i for i, (_, c) in enumerate(merged) if _distance(c, shade) < 48), None)
        if near is None:
            merged.append((share, shade))
        else:
            merged[near] = (merged[near][0] + share, merged[near][1])
    colors = [rgb3 for share, rgb3 in sorted(merged, reverse=True) if share / len(pixels) >= 0.04]
    return tuple(f"#{r:02x}{g:02x}{b:02x}" for r, g, b in colors[:_MOST_COLORS])


def _distance(a: tuple[int, int, int], b: tuple[int, int, int]) -> float:
    return float(sum((x - y) ** 2 for x, y in zip(a, b, strict=True)) ** 0.5)
