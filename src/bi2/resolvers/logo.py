"""The business's logo: the image its page ranks most logo-like, once it's checked to be one.

The ranking in evidence/logos.py says which image looks most like the logo. This accepts it when
it clearly leads, downloads it, and checks that the file is a real image of a logo's shape and
size. An inline SVG logo has no file of its own, so it's cut out of the screenshot instead.
"""

from typing import Final

from bi2.core.context import RunContext
from bi2.core.errors import FetchError
from bi2.core.models import Evidence, Logo, LogoCandidate, LogoResult
from bi2.core.urls import site_folder
from bi2.resolvers.cascade import Escalate, Resolved, run_cascade
from bi2.resolvers.images import crop, inspect_image, logo_problem

_MAX_LOGO_BYTES: Final = 5_000_000
_TRIES: Final = 3  # candidates checked before giving up
_LESS_SURE_PER_TRY: Final = 0.15  # each candidate that had to be skipped lowers the confidence


def _confidence(top: LogoCandidate, runner_up: int) -> float:
    """How sure the ranking is: the top candidate's points, and its lead over the next."""
    lead = top.points - runner_up
    if top.points >= 10 and lead >= 3:
        return 0.9
    if top.points >= 7 and lead >= 2:
        return 0.85
    return 0.7 if top.points >= 5 else 0.5


def _in_order(ranked: list[LogoCandidate]) -> list[LogoCandidate]:
    """The candidates to check, best first. When the best is an inline image with no file of
    its own, the logo file the structured data names goes first: the business's own file for
    the logo its page shows."""
    order = [candidate for candidate in ranked if candidate.kind != "icon"]
    declared = next((c for c in order if c.declared and c.url), None)
    if order and order[0].url is None and declared is not None:
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


async def logo_from_the_page(ev: Evidence, ctx: RunContext) -> Resolved[Logo] | Escalate:
    """The page's most logo-like image that checks out as one."""
    ranked = list(ev.logo_candidates)
    order = _in_order(ranked)
    if not order:
        return Escalate("no image on the page looks like a logo")
    sure = _confidence(ranked[0], ranked[1].points if len(ranked) > 1 else 0)
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
            evidence=(candidate.url or "cut out of the screenshot", *skipped),
        )
    return Escalate("no candidate checked out: " + "; ".join(skipped))


async def resolve_logo(ev: Evidence, ctx: RunContext) -> LogoResult:
    """The business's logo. Asking a vision model "which number is the logo?" joins later."""
    return await run_cascade([logo_from_the_page], ev, ctx)
