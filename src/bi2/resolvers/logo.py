"""The business's logo: the image its page ranks most logo-like, once it's checked to be one.

The ranking in evidence/logos.py says which image looks most like the logo. This accepts it when
it clearly leads, downloads it, and checks that the file is a real image of a logo's shape and
size. An inline SVG logo is saved as its own code, which the page reader keeps. Only a logo with
neither a file nor code, such as one drawn with CSS, is cut out of the screenshot.
"""

import re
from typing import Final
from urllib.parse import unquote, urlsplit

from bi2.core.context import RunContext
from bi2.core.errors import FetchError
from bi2.core.models import Evidence, Logo, LogoCandidate, LogoResult
from bi2.core.urls import site_folder
from bi2.resolvers.cascade import Escalate, Resolved, run_cascade
from bi2.resolvers.images import crop, inspect_image, logo_problem

_MAX_LOGO_BYTES: Final = 5_000_000
_TRIES: Final = 3  # candidates checked before giving up
_LESS_SURE_PER_TRY: Final = 0.15  # each candidate that had to be skipped lowers the confidence


# Words that name a version of a logo file rather than another image: mec-logo-desktop.svg
# and mec-logo-mobile.svg are the same logo as mec-logo.svg. Numbers don't: logos-01.jpg and
# logos-05.jpg are usually a row of partners' logos.
_VERSION = re.compile(
    r"[-_.@](?:desktop|mobile|tablet|white|black|dark|light|colou?r|reversed?|inverse|alt|"
    r"header|footer|small|large|sm|lg|retina|\d+x)$"
)


def _stem(url: str | None) -> str:
    """A logo file's name without its type and version words, to tell versions of one logo."""
    if not url:
        return ""
    name = unquote(urlsplit(url).path.rsplit("/", 1)[-1]).lower().rsplit(".", 1)[0]
    while (shorter := _VERSION.sub("", name)) != name:
        name = shorter
    return name


def _runner_up(ranked: list[LogoCandidate]) -> int:
    """The points of the best candidate that isn't another version of the top one's file."""
    top = _stem(ranked[0].url)
    if top == "logo":
        top = ""  # too common a name to tell, like a partner's logo.png
    others = (c.points for c in ranked[1:] if not (top and _stem(c.url) == top))
    return next(others, 0)


def _confidence(top: LogoCandidate, runner_up: int) -> float:
    """How sure the ranking is: the top candidate's points, and its lead over the next."""
    lead = top.points - runner_up
    if top.points >= 10 and lead >= 3:
        return 0.9
    if top.points >= 7 and lead >= 2:
        return 0.85
    return 0.7 if top.points >= 5 else 0.5


def _in_order(ranked: list[LogoCandidate]) -> list[LogoCandidate]:
    """The candidates to check, best first. When the best has neither a file nor code of its
    own, so it would be cut out of the screenshot, the logo file the structured data names goes
    first: the business's own file. An inline SVG's own code stays first, since the declared
    file can be another mark, like Mejuri's monogram for its wordmark."""
    order = [candidate for candidate in ranked if candidate.kind != "icon"]
    declared = next((c for c in order if c.declared and c.url), None)
    if order and order[0].url is None and not order[0].svg and declared is not None:
        order.remove(declared)
        order.insert(0, declared)
    return order


def _signs(candidate: LogoCandidate) -> str:
    signs = [
        sign
        for sign, present in (
            ("links home", candidate.links_home),
            ("in the header", candidate.in_header),
            ("named by the structured data", candidate.declared),
        )
        if present
    ]
    return ", ".join(signs) or candidate.kind


def _where(candidate: LogoCandidate) -> str:
    if candidate.url:
        return candidate.url
    return "saved from the page's SVG code" if candidate.svg else "cut out of the screenshot"


async def _logo_file(
    candidate: LogoCandidate, ev: Evidence, ctx: RunContext
) -> tuple[str | None, str]:
    """Save the candidate's image and return its path, or None and why it can't be the logo."""
    folder = site_folder(ev.page.url)
    if candidate.url:
        try:
            data = await ctx.downloader.download(
                candidate.url, max_bytes=_MAX_LOGO_BYTES, referer=ev.page.final_url
            )
        except FetchError as exc:
            return None, f"couldn't be downloaded ({exc})"
    elif candidate.svg:
        data = candidate.svg.encode("utf-8")
    else:
        if ev.screenshot_file is None or candidate.box is None:
            return None, "has no file of its own and isn't on the screenshot"
        try:
            screenshot = await ctx.files.read(ev.screenshot_file)
        except OSError:
            return None, "has no file of its own, and the screenshot wasn't saved"
        cut = crop(screenshot, candidate.box)
        if cut is None:
            return None, "has no file of its own and isn't on the screenshot"
        data = cut
    info = inspect_image(data)
    problem = logo_problem(info, declared=candidate.declared)
    if problem or info is None:
        return None, problem or "isn't an image"
    return await ctx.files.save(f"{folder}/logo.{info.extension}", data), ""


async def save_logo_file(url: str, ev: Evidence, ctx: RunContext) -> tuple[str | None, str]:
    """Download a logo file the business names as its own, check that it's a logo, and save
    it: its path, or None and why it can't be the logo."""
    named = LogoCandidate(number=1, kind="structured_data", url=url, declared=True)
    return await _logo_file(named, ev, ctx)


async def logo_from_the_page(ev: Evidence, ctx: RunContext) -> Resolved[Logo] | Escalate:
    """The page's most logo-like image that checks out as one."""
    ranked = list(ev.logo_candidates)
    order = _in_order(ranked)
    if not order:
        return Escalate("no image on the page looks like a logo")
    sure = _confidence(ranked[0], _runner_up(ranked))
    icon = next((c.url for c in ranked if c.kind == "icon" and c.url), None)
    skipped: list[str] = []
    for tries, candidate in enumerate(order[:_TRIES]):
        saved, problem = await _logo_file(candidate, ev, ctx)
        if saved is None:
            skipped.append(f"candidate {candidate.number} {problem}")
            continue
        return Resolved(
            value=Logo(url=candidate.url, image_file=saved, icon_url=icon),
            confidence=max(0.0, sure - _LESS_SURE_PER_TRY * tries),
            source=f"logo candidate {candidate.number} ({_signs(candidate)})",
            evidence=(_where(candidate), *skipped),
        )
    return Escalate("no candidate checked out: " + "; ".join(skipped))


async def resolve_logo(ev: Evidence, ctx: RunContext) -> LogoResult:
    """The business's logo. Asking a vision model "which number is the logo?" joins later."""
    return await run_cascade([logo_from_the_page], ev, ctx)
