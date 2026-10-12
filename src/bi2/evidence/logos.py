"""Images that might be the business's logo, ranked by how much they look like one.

Each candidate gets a number, so a model shown the screenshot can be asked "which number is
the logo?" when the ranking alone isn't sure.
"""

import re
from collections.abc import Iterable
from typing import Final, Literal, NamedTuple
from urllib.parse import unquote, urlsplit

from bi2.core.models import Box, LogoCandidate, PageMeta, RenderedImage, StructuredData
from bi2.core.text import fold, normalize_company_name
from bi2.core.urls import absolute_url, image_key, registrable_domain
from bi2.evidence.document import Document, attribute

_KEEP: Final = 8

# Words in an image's address, label or class that mean it's something other than the logo.
_NOT_LOGO: Final = re.compile(
    r"facebook|instagram|twitter|tiktok|youtube|linkedin|pinterest|whatsapp|social|"
    r"payment|visa|mastercard|amex|paypal|klarna|afterpay|"
    r"cart|basket|search|hamburger|menu-icon|close|arrow|chevron|caret|flag|avatar|"
    r"spinner|placeholder|award|trustpilot|app-?store|google-?play"
)

# Points for each sign that an image is the logo, or isn't.
_LINKS_HOME, _IN_HEADER, _SAYS_LOGO, _SAYS_NAME = 4, 3, 3, 2
_DECLARED, _SEEN_AGAIN = 3, 1  # named as the logo by structured data; drawn more than once


class _Scored(NamedTuple):
    points: int
    order: int  # page order, which settles ties
    kind: Literal["img", "svg", "background", "structured_data", "icon"]
    url: str | None
    alt: str
    css_class: str
    box: Box | None
    in_header: bool
    links_home: bool


def _brand_words(meta: PageMeta, structured: StructuredData, page_url: str) -> set[str]:
    """Words of the business's name, to spot in an image's label or file name."""
    names = (structured.name or "", meta.site_name, registrable_domain(page_url).split(".")[0])
    return {
        word for name in names for word in normalize_company_name(name).split() if len(word) >= 4
    }


def _file_name(url: str) -> str:
    return unquote(urlsplit(url).path.rsplit("/", 1)[-1])


def _points(image: RenderedImage, brand: set[str]) -> int:
    """How much an image drawn on the page looks like the logo."""
    words = fold(f"{image.alt} {image.css_class} {image.element_id} {_file_name(image.url)}")
    # A header's logo sits at the top. Images far down in a "header" are in a drop-down menu.
    near_top = image.box is None or image.box.y < 400
    points = _LINKS_HOME * image.links_home + _IN_HEADER * (image.in_header and near_top)
    points += _SAYS_LOGO * ("logo" in words) + _SAYS_NAME * any(word in words for word in brand)
    if _NOT_LOGO.search(words):
        points -= 4
    box = image.box
    if box is not None:
        if box.width == 0 or box.height == 0:
            points -= 1  # not shown, often the logo for another screen size
        elif box.width < 16 or box.height < 10:
            points -= 3  # an icon
        elif box.width > 900 or box.height > 500:
            points -= 3  # a photo
        else:
            points += (box.y < 300) + (40 <= box.width <= 600 and 16 <= box.height <= 300)
    return points


def _icons(doc: Document, base_url: str) -> Iterable[tuple[str, int]]:
    """The site's icons, with points: the larger app icon over the browser tab's."""
    selector = 'link[rel~="icon" i], link[rel~="apple-touch-icon" i], link[rel~="apple-touch-icon-precomposed" i]'
    for link in doc.css(selector):
        url = absolute_url(base_url, attribute(link, "href"))
        if url:
            yield url, 1 if "apple" in attribute(link, "rel").lower() else 0


def _combine(found: list[_Scored]) -> list[_Scored]:
    """One candidate per image, however many times or sizes it appears, keeping the best
    placed copy. Inline SVGs have no address, so each one stays separate."""
    by_image: dict[str, list[_Scored]] = {}
    unique: list[_Scored] = []
    for candidate in found:
        if candidate.url is None:
            unique.append(candidate)
        else:
            by_image.setdefault(image_key(candidate.url), []).append(candidate)
    for copies in by_image.values():
        drawn = [copy for copy in copies if copy.kind not in ("structured_data", "icon")]
        best = max(drawn or copies, key=lambda copy: (copy.points, -copy.order))
        bonus = _DECLARED * any(copy.kind == "structured_data" for copy in copies)
        bonus += _SEEN_AGAIN * (len(drawn) > 1)
        unique.append(best._replace(points=best.points + bonus, order=min(c.order for c in copies)))
    return unique


def extract_logo_candidates(
    images: Iterable[RenderedImage],
    doc: Document,
    base_url: str,
    *,
    meta: PageMeta,
    structured: StructuredData,
) -> tuple[LogoCandidate, ...]:
    """The images most likely to be the logo, best first and numbered from 1: images drawn on
    the page, the logo the structured data names, and the site's icons."""
    brand = _brand_words(meta, structured, base_url)
    found: list[_Scored] = []
    if structured.logo_url:
        found.append(
            _Scored(
                _DECLARED, 0, "structured_data", structured.logo_url, "", "", None, False, False
            )
        )
    for order, image in enumerate(images, start=1):
        url = image.url if image.url.startswith(("http://", "https://")) else None
        if url is None and image.kind != "svg":
            continue  # a placeholder or an inline data image, with no address to use
        found.append(
            _Scored(
                _points(image, brand),
                order,
                image.kind,
                url,
                image.alt,
                image.css_class,
                image.box,
                image.in_header,
                image.links_home,
            )
        )
    found += [
        _Scored(points, 10_000 + n, "icon", url, "", "", None, False, False)
        for n, (url, points) in enumerate(_icons(doc, base_url))
    ]
    ranked = sorted(_combine(found), key=lambda candidate: (-candidate.points, candidate.order))
    return tuple(
        LogoCandidate(
            number=number,
            kind=candidate.kind,
            url=candidate.url,
            alt=candidate.alt,
            css_class=candidate.css_class,
            box=candidate.box,
            in_header=candidate.in_header,
            links_home=candidate.links_home,
        )
        for number, candidate in enumerate(ranked[:_KEEP], start=1)
    )
