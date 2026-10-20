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
from bi2.evidence.platforms import Profile, platforms

_KEEP: Final = 8

# Words in an image's address, label or class that mean it's something other than the logo.
_NOT_LOGO: Final = re.compile(
    r"facebook|instagram|twitter|tiktok|youtube|linkedin|pinterest|whatsapp|social|"
    r"payment|visa|mastercard|amex|paypal|klarna|afterpay|"
    r"cart|basket|search|hamburger|menu-icon|close|arrow|chevron|caret|flag|avatar|"
    r"spinner|placeholder|award|trustpilot|app-?store|google-?play|"
    r"texture|grain|pattern|noise"  # a fill behind or inside the logo, like paper grain
)

# Stand-ins a site shows when an image is missing, like Waterstones' hidden "default image",
# cover404.png. They're pictures of nothing, so they're never candidates. A 404 counts only
# right before the file type, since file names made of hex IDs often hold one, like 404e272d.
_STAND_IN: Final = re.compile(
    r"default[ _-]?image|no[ _-]?image|image[ _-]?not[ _-]?found|"
    r"(?<![0-9])404\.(?:png|jpe?g|gif|svg|webp|avif)\b"
)

# Points for each sign that an image is the logo, or isn't.
_LINKS_HOME, _IN_HEADER, _SAYS_LOGO, _SAYS_NAME = 4, 3, 3, 2
_DECLARED, _SEEN_AGAIN = 3, 1  # named as the logo by structured data; drawn more than once
# A logo drawn as styled text can only be cut out of the screenshot, so a file of the logo, or
# its code, counts for more.
_ONLY_TEXT = 3
_PROFILE_PICTURE = 3  # on a platform's page, the business's profile picture is its logo


class _Scored(NamedTuple):
    points: int
    order: int  # page order, which settles ties
    kind: Literal["img", "svg", "background", "text", "structured_data", "icon"]
    url: str | None
    alt: str
    css_class: str
    box: Box | None
    in_header: bool
    links_home: bool
    declared: bool = False  # named as the logo by the structured data
    svg: str = ""  # an inline SVG's own code


def _words_of(names: Iterable[str]) -> set[str]:
    return {
        word for name in names for word in normalize_company_name(name).split() if len(word) >= 4
    }


def _brand_words(meta: PageMeta, structured: StructuredData, page_url: str) -> set[str]:
    """Words of the business's name, to spot in an image's label or file name."""
    return _words_of(
        (structured.name or "", meta.site_name, registrable_domain(page_url).split(".")[0])
    )


def _file_name(url: str) -> str:
    return unquote(urlsplit(url).path.rsplit("/", 1)[-1])


def _words(image: RenderedImage) -> str:
    return fold(f"{image.alt} {image.css_class} {image.element_id} {_file_name(image.url)}")


def _size_points(box: Box | None, *, in_logo_link: bool = False) -> int:
    """Points for where an image was drawn and how big it was. A small image in a link labeled
    as the logo is a slim logo, like Mejuri's wordmark, not an icon."""
    if box is None:
        return 0
    if box.width == 0 or box.height == 0:
        return -1  # not shown, often the logo for another screen size
    if (box.width < 16 or box.height < 10) and not in_logo_link:
        return -3  # an icon
    if box.width > 900 or box.height > 500:
        return -3  # a photo
    return (box.y < 300) + (40 <= box.width <= 600 and 16 <= box.height <= 300)


def _points(image: RenderedImage, brand: set[str]) -> int:
    """How much an image drawn on the business's own site looks like its logo."""
    words = _words(image)
    # A header's logo sits at the top. Images far down in a "header" are in a drop-down menu.
    near_top = image.box is None or image.box.y < 400
    points = _LINKS_HOME * image.links_home + _IN_HEADER * (image.in_header and near_top)
    points += _SAYS_LOGO * ("logo" in words) + _SAYS_NAME * any(word in words for word in brand)
    if _NOT_LOGO.search(words):
        points -= 4
    return points + _size_points(image.box, in_logo_link="logo" in fold(image.link_label))


def _platforms_own(image: RenderedImage, platform_name: str) -> bool:
    """Whether an image on a platform's page is the platform's, like its logo in the header."""
    return image.links_home or fold(platform_name) in fold(image.alt)


def _profile_points(image: RenderedImage, brand: set[str]) -> int:
    """How much an image on a platform's page looks like the business's logo, which there is
    its profile picture."""
    words = _words(image)
    points = _SAYS_NAME * any(word in words for word in brand)
    points += _PROFILE_PICTURE * ("profile" in words)
    return points + _size_points(image.box)


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
        declared = any(copy.declared for copy in copies)
        bonus = _DECLARED * declared + _SEEN_AGAIN * (len(drawn) > 1)
        first = min(copy.order for copy in copies)
        unique.append(best._replace(points=best.points + bonus, order=first, declared=declared))
    return unique


def extract_logo_candidates(
    images: Iterable[RenderedImage],
    doc: Document,
    base_url: str,
    *,
    meta: PageMeta,
    structured: StructuredData,
    profile: Profile | None = None,
    profile_name: str | None = None,
) -> tuple[LogoCandidate, ...]:
    """The images most likely to be the logo, best first and numbered from 1: images drawn on
    the page, the logo the structured data names, and the site's icons. On a platform's page,
    given its profile, the business's profile picture counts instead of the platform's logo."""
    if profile is None:
        brand = _brand_words(meta, structured, base_url)
    else:
        brand = _words_of((profile_name or "", profile.handle.lstrip("@")))
    found: list[_Scored] = []
    if structured.logo_url and _file_name(structured.logo_url).lower().endswith(".ico"):
        # A browser tab's icon, which some sites name as their logo, like Warby Parker.
        found.append(_Scored(0, 0, "icon", structured.logo_url, "", "", None, False, False))
    elif structured.logo_url:
        found.append(
            _Scored(
                _DECLARED,
                0,
                "structured_data",
                structured.logo_url,
                "",
                "",
                None,
                False,
                False,
                declared=True,
            )
        )
    for order, image in enumerate(images, start=1):
        url = image.url if image.url.startswith(("http://", "https://")) else None
        if url is None and image.kind not in ("svg", "text"):
            continue  # a placeholder or an inline data image, with no address to use
        if _STAND_IN.search(_words(image)):
            continue
        if profile is None:
            points = _points(image, brand) - _ONLY_TEXT * (image.kind == "text")
        elif _platforms_own(image, platforms()[profile.platform].name):
            continue
        else:
            points = _profile_points(image, brand)
        found.append(
            _Scored(
                points,
                order,
                image.kind,
                url,
                image.alt,
                image.css_class,
                image.box,
                image.in_header,
                image.links_home,
                svg=image.svg,
            )
        )
    if profile is None:  # a platform's icons are its own
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
            declared=candidate.declared,
            points=candidate.points,
            svg=candidate.svg,
        )
        for number, candidate in enumerate(ranked[:_KEEP], start=1)
    )
