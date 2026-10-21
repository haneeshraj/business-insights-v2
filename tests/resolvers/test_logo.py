"""Tests for choosing and checking the logo."""

from typing import Any

from bi2.core.models import Box, Evidence, LogoCandidate, LogoResult, PageInfo, PageKind, Status
from bi2.resolvers.logo import resolve_logo
from tests.fakes import MemoryFiles, fake_context
from tests.resolvers.images import picture, screenshot_with_logo

URL = "https://example-cafe.ca/"
TOP_SPOT = Box(x=20, y=10, width=160, height=60)


def _candidate(number: int, points: int, url: str | None = None, **fields: Any) -> LogoCandidate:
    kind = fields.pop("kind", "img" if url else "svg")
    return LogoCandidate(number=number, kind=kind, url=url, points=points, **fields)


async def _resolve(
    candidates: list[LogoCandidate],
    downloads: dict[str, bytes] | None = None,
    screenshot: bytes | None = None,
) -> tuple[LogoResult, MemoryFiles]:
    files = MemoryFiles()
    if screenshot:
        await files.save("example-cafe.ca/screenshot.jpg", screenshot)
    ev = Evidence(
        page=PageInfo(url=URL, final_url=URL, kind=PageKind.OWN_WEBSITE),
        logo_candidates=tuple(candidates),
        screenshot_file="example-cafe.ca/screenshot.jpg" if screenshot else None,
    )
    return await resolve_logo(ev, fake_context(downloads=downloads, files=files)), files


async def test_a_clear_winner_is_downloaded_checked_and_saved() -> None:
    result, files = await _resolve(
        [
            _candidate(1, 14, f"{URL}logo.png", in_header=True, links_home=True),
            _candidate(2, 5, f"{URL}hero.jpg"),
            _candidate(3, 1, f"{URL}apple-touch-icon.png", kind="icon"),
        ],
        downloads={f"{URL}logo.png": picture(120, 40)},
    )
    assert (result.status, result.confidence) == (Status.OK, 0.9)
    assert result.value is not None
    assert result.value.url == f"{URL}logo.png"
    assert result.value.image_file == "example-cafe.ca/logo.png"
    assert result.value.icon_url == f"{URL}apple-touch-icon.png"
    assert result.source == "logo candidate 1 (links home, in the header)"
    assert "example-cafe.ca/logo.png" in files.files


async def test_a_tracker_is_skipped_for_the_next_candidate_with_less_confidence() -> None:
    result, _ = await _resolve(
        [_candidate(1, 14, f"{URL}pixel.gif"), _candidate(2, 6, f"{URL}logo.png")],
        downloads={f"{URL}pixel.gif": picture(1, 1, "GIF"), f"{URL}logo.png": picture(120, 40)},
    )
    assert result.status is Status.NEEDS_REVIEW
    assert result.value is not None
    assert result.value.url == f"{URL}logo.png"
    assert "candidate 1 is a one-pixel tracker or placeholder" in result.evidence


async def test_an_inline_logo_is_cut_out_of_the_screenshot() -> None:
    result, files = await _resolve(
        [_candidate(1, 13, box=TOP_SPOT, in_header=True, links_home=True), _candidate(2, 4)],
        screenshot=screenshot_with_logo(20, 10, 160, 60),
    )
    assert result.status is Status.OK
    assert result.value is not None
    assert (result.value.url, result.value.image_file) == (None, "example-cafe.ca/logo.png")
    assert result.evidence[0] == "cut out of the screenshot"
    assert "example-cafe.ca/logo.png" in files.files


async def test_an_svg_logo_is_saved_as_its_own_code() -> None:
    code = '<svg xmlns="http://www.w3.org/2000/svg" width="120" height="40"><rect/></svg>'
    result, files = await _resolve(
        [_candidate(1, 13, box=TOP_SPOT, in_header=True, links_home=True, svg=code)],
        screenshot=screenshot_with_logo(20, 10, 160, 60),
    )
    assert result.value is not None
    assert result.value.image_file == "example-cafe.ca/logo.svg"
    assert files.files["example-cafe.ca/logo.svg"] == code.encode()
    assert result.evidence[0] == "saved from the page's SVG code"


async def test_the_declared_logo_file_goes_before_an_inline_image() -> None:
    declared = f"{URL}brand/logo.png"
    result, _ = await _resolve(
        [
            _candidate(1, 13, box=TOP_SPOT, in_header=True, links_home=True),
            _candidate(2, 6, declared, kind="structured_data", declared=True),
        ],
        downloads={declared: picture(300, 100)},
    )
    assert result.status is Status.OK
    assert result.value is not None
    assert result.value.url == declared


async def test_an_svg_logos_own_code_goes_before_the_declared_file() -> None:
    declared = f"{URL}brand/monogram.png"
    code = '<svg xmlns="http://www.w3.org/2000/svg" width="120" height="40"><rect/></svg>'
    wordmark = _candidate(1, 13, box=TOP_SPOT, in_header=True, links_home=True, svg=code)
    result, _ = await _resolve(
        [
            wordmark,
            _candidate(2, 6, declared, kind="structured_data", declared=True),
        ],
        downloads={declared: picture(300, 300)},
    )
    assert result.value is not None
    assert result.value.url is None  # saved from the page's code, not the declared file


async def test_other_versions_of_the_logo_file_dont_make_it_a_close_call() -> None:
    top = f"{URL}images/cafe-logo-desktop.svg"
    result, _ = await _resolve(
        [_candidate(1, 12, top), _candidate(2, 11, f"{URL}images/cafe-logo.svg")],
        downloads={top: picture(120, 40)},
    )
    assert result.status is Status.OK


async def test_a_row_of_numbered_images_is_still_a_close_call() -> None:
    first = f"{URL}images/partner-logos_01.jpg"
    result, _ = await _resolve(
        [_candidate(1, 9, first), _candidate(2, 9, f"{URL}images/partner-logos_05.jpg")],
        downloads={first: picture(200, 200)},
    )
    assert result.status is Status.NEEDS_REVIEW


async def test_a_close_call_needs_review() -> None:
    result, _ = await _resolve(
        [_candidate(1, 6, f"{URL}a.png"), _candidate(2, 5, f"{URL}b.png")],
        downloads={f"{URL}a.png": picture(120, 40)},
    )
    assert result.status is Status.NEEDS_REVIEW


async def test_when_nothing_checks_out_the_logo_is_not_found() -> None:
    result, _ = await _resolve([_candidate(1, 14, f"{URL}gone.png"), _candidate(2, 3)])
    assert result.status is Status.NOT_FOUND
    assert "candidate 1 couldn't be downloaded" in (result.steps[0].detail or "")


def test_color_versions_of_one_logo_file_are_the_same_logo() -> None:
    from bi2.core.models import LogoCandidate
    from bi2.resolvers.logo import same_logo

    def candidate(number: int, url: str) -> LogoCandidate:
        return LogoCandidate(number=number, kind="img", url=url)

    brown = candidate(1, "https://granjaviader.cat/uploads/logo-brown-2.png")
    white = candidate(2, "https://granjaviader.cat/uploads/logo-blanc-2.png")
    partner = candidate(3, "https://granjaviader.cat/uploads/visa.png")
    assert same_logo(brown, white)
    assert not same_logo(brown, partner)


def test_a_bare_logo_file_name_is_too_common_to_be_the_same_logo() -> None:
    from bi2.core.models import LogoCandidate
    from bi2.resolvers.logo import same_logo

    partner = LogoCandidate(
        number=1, kind="img", url="https://example-cafe.ca/files/partners/logo.png"
    )
    white = LogoCandidate(number=2, kind="img", url="https://example-cafe.ca/files/logo-white.svg")
    assert not same_logo(partner, white)
