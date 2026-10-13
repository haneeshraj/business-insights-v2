"""Tests for ranking the images that might be the logo."""

from typing import Any

from bi2.core.models import Box, LogoCandidate, PageMeta, RenderedImage, StructuredData
from bi2.evidence.document import parse_html
from bi2.evidence.logos import extract_logo_candidates

BASE = "https://example-cafe.ca/"
META = PageMeta(site_name="Example Cafe")
HEADER_SPOT = Box(x=20, y=10, width=160, height=60)


def _image(url: str, **fields: Any) -> RenderedImage:
    return RenderedImage.model_validate({"kind": "img", "url": url, "box": HEADER_SPOT, **fields})


def _rank(
    images: list[RenderedImage], html: str = "", structured: StructuredData | None = None
) -> tuple[LogoCandidate, ...]:
    return extract_logo_candidates(
        images, parse_html(html), BASE, meta=META, structured=structured or StructuredData()
    )


def test_the_header_logo_that_links_home_comes_first() -> None:
    candidates = _rank(
        [
            _image(f"{BASE}hero.jpg", alt="Our cafe", box=Box(x=0, y=400, width=1280, height=600)),
            _image(
                f"{BASE}icons/facebook.png",
                alt="Facebook",
                in_header=True,
                box=Box(x=900, y=10, width=24, height=24),
            ),
            _image(
                f"{BASE}images/logo_300x.png", alt="Example Cafe", in_header=True, links_home=True
            ),
        ]
    )
    assert [c.url for c in candidates] == [
        f"{BASE}images/logo_300x.png",
        f"{BASE}icons/facebook.png",
        f"{BASE}hero.jpg",
    ]
    assert [c.number for c in candidates] == [1, 2, 3]


def test_images_far_down_in_a_header_menu_dont_count_as_header_images() -> None:
    candidates = _rank(
        [
            _image(
                f"{BASE}menu/product-logo.png",
                in_header=True,
                box=Box(x=20, y=2000, width=120, height=40),
            ),
            _image(f"{BASE}brand.svg", alt="Example Cafe", in_header=True),
        ]
    )
    assert candidates[0].url == f"{BASE}brand.svg"


def test_copies_of_one_image_become_one_candidate() -> None:
    candidates = _rank(
        [
            _image(f"{BASE}logo-300x100.png", in_header=True, links_home=True),
            _image(f"{BASE}logo.png?v=2", box=Box(x=20, y=3000, width=120, height=40)),
        ],
        structured=StructuredData(logo_url=f"{BASE}logo.png"),
    )
    assert len(candidates) == 1
    assert candidates[0].in_header  # the best-placed copy is the one kept
    assert candidates[0].kind == "img"


def test_stand_ins_for_a_missing_image_are_never_candidates() -> None:
    hidden = Box(x=0, y=0, width=0, height=0)
    stand_in = _image(
        f"{BASE}images/cover404.png",
        alt="default image",
        in_header=True,
        links_home=True,
        box=hidden,
    )
    banner = _image(
        f"{BASE}promo-280x275.jpg", alt="Christmas", box=Box(x=380, y=3490, width=240, height=238)
    )
    assert [c.url for c in _rank([stand_in, banner])] == [f"{BASE}promo-280x275.jpg"]
    named_by_id = _image(f"{BASE}uploads/1781042768620-404e272d.webp")  # a 404 in an ID
    assert len(_rank([named_by_id])) == 1


def test_inline_svgs_and_icons_count_but_placeholders_dont() -> None:
    svg = RenderedImage(
        kind="svg", alt="Example Cafe wordmark", box=HEADER_SPOT, in_header=True, links_home=True
    )
    placeholder = _image("data:image/gif;base64,R0lGODlhAQABAAAAACw=")
    icons = '<link rel="icon" href="/favicon.ico"><link rel="apple-touch-icon" href="/touch.png">'
    candidates = _rank([svg, placeholder], icons)
    assert [(c.kind, c.url) for c in candidates] == [
        ("svg", None),
        ("icon", f"{BASE}touch.png"),
        ("icon", f"{BASE}favicon.ico"),
    ]
