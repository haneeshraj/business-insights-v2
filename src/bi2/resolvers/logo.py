"""The business's logo: the image its page ranks most logo-like, once it's checked to be one.

The ranking in evidence/logos.py says which image looks most like the logo. This accepts it when
it clearly leads, downloads it, and checks that the file is a real image of a logo's shape and
size. An inline SVG logo is saved as its own code, which the page reader keeps. Only a logo with
neither a file nor code, such as one drawn with CSS, is cut out of the screenshot.
"""

import re
from typing import Final
from urllib.parse import unquote, urlsplit

from bi2.core.asking import Ask, Choice
from bi2.core.context import RunContext
from bi2.core.errors import FetchError
from bi2.core.models import Evidence, Logo, LogoCandidate, LogoResult
from bi2.core.urls import site_folder
from bi2.resolvers.asking import NO_MODEL, NO_SECOND, NONE, ask_decider, confidence, site_lines
from bi2.resolvers.cascade import Escalate, Resolved, Step, run_cascade
from bi2.resolvers.images import crop, inspect_image, logo_problem, number_boxes

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


# The most candidates numbered on the screenshot for a model: past these, the boxes crowd it.
_MOST_SHOWN: Final = 8
_PICK_VERSION: Final = "1"
_PICK: Final = (
    "Which numbered box in `screenshot` marks the business's own logo: the brand mark or "
    "name it shows as its own, usually at the top of the page? Not a partner's or a "
    "supplier's logo, a product photo, a social media or payment icon, or an award badge."
)
_KINDS: Final = {
    "img": "an image",
    "svg": "a drawing",
    "background": "a CSS image",
    "text": "styled text",
}


def _describe(candidate: LogoCandidate) -> str:
    """What the page says about a candidate, for a model to read beside its box."""
    parts = [_KINDS.get(candidate.kind, candidate.kind)]
    if candidate.in_header:
        parts.append("in the header")
    if candidate.links_home:
        parts.append("links to the home page")
    if candidate.alt:
        parts.append(f'labeled "{candidate.alt[:80]}"')
    if candidate.url:
        parts.append("file " + candidate.url.rsplit("/", 1)[-1].split("?")[0][:60])
    return ", ".join(parts)


def _place(candidate: LogoCandidate) -> tuple[int, float]:
    box = candidate.box
    return (round(box.y / 20), box.x) if box else (0, 0.0)


def _logo_ask(ev: Evidence, shown: list[LogoCandidate], screenshot: bytes) -> Ask:
    """Which numbered box is the logo. Options run top to bottom, then left to right, rather
    than in the rules' order, so a model's lean toward the first option doesn't just repeat
    the rules."""
    options = {str(c.number): f"box {c.number}: {_describe(c)}" for c in sorted(shown, key=_place)}
    options[NONE] = "No box marks the business's own logo"
    lines = [*site_lines(ev), "The numbered boxes in `screenshot` mark images on the page."]
    return Ask(
        task="logo_pick",
        version=_PICK_VERSION,
        state="\n".join(lines),
        questions={"logo": Choice(instructions=_PICK, options=options)},
        images={"screenshot": screenshot},
    )


async def _numbered_screenshot(
    ev: Evidence, ctx: RunContext
) -> tuple[bytes, list[LogoCandidate]] | str:
    """The screenshot with the likeliest candidates numbered on it, or why there's none."""
    if ev.screenshot_file is None:
        return "there's no screenshot to number the candidates on"
    boxed = [c for c in ev.logo_candidates if c.kind != "icon" and c.box and c.box.width > 0]
    if not boxed:
        return "no candidate is drawn on the page"
    try:
        screenshot = await ctx.files.read(ev.screenshot_file)
    except OSError:
        return "the screenshot wasn't saved"
    boxes = [(c.number, c.box) for c in boxed[:_MOST_SHOWN] if c.box]
    image, drawn = number_boxes(screenshot, boxes)
    if not drawn:
        return "no candidate is on the screenshot"
    await ctx.files.save(f"{site_folder(ev.page.url)}/logo-candidates.jpg", image)
    return image, [c for c in boxed if c.number in drawn]


def _logo_by(*, second: bool) -> Step[Logo]:
    """A step that asks a model which numbered box is the logo: the Decider, or with `second`
    the second model, for a second opinion."""

    async def ask(ev: Evidence, ctx: RunContext) -> Resolved[Logo] | Escalate:
        if (ctx.second if second else ctx.decider) is None:
            return Escalate(NO_SECOND if second else NO_MODEL)
        numbered = await _numbered_screenshot(ev, ctx)
        if isinstance(numbered, str):
            return Escalate(numbered)
        image, shown = numbered
        decision = await ask_decider(_logo_ask(ev, shown, image), ctx, second=second)
        if isinstance(decision, str):
            return Escalate(decision)
        picked = decision.picked("logo")
        probability = picked.probability(picked.choice)
        if picked.choice == NONE:
            why = f"{decision.model} says no box is the logo ({probability:.2f})"
            return Escalate(why, cost=decision.cost)
        candidate = next(c for c in shown if str(c.number) == picked.choice)
        saved, problem = await _logo_file(candidate, ev, ctx)
        if saved is None:
            why = f"{decision.model} picked candidate {candidate.number}, which {problem}"
            return Escalate(why, cost=decision.cost)
        rules = _in_order(list(ev.logo_candidates))
        agrees = bool(rules) and rules[0].number == candidate.number
        icon = next((c.url for c in ev.logo_candidates if c.kind == "icon" and c.url), None)
        how = ", as the rules ranked it" if agrees else ""
        return Resolved(
            value=Logo(url=candidate.url, image_file=saved, icon_url=icon),
            confidence=confidence(probability, agrees=agrees),
            source=f"{decision.model}: logo candidate {candidate.number} on the numbered "
            f"screenshot ({probability:.2f}{how})",
            evidence=(_where(candidate),),
            cost=decision.cost,
        )

    ask.__name__ = "logo_by_second_opinion" if second else "logo_by_decider"
    return ask


async def logo_from_known_file(ev: Evidence, ctx: RunContext) -> Resolved[Logo] | Escalate:
    """The logo file Wikidata names for a big business, when the page's own images didn't
    settle it: a programmatic source that needs no page at all."""
    known = ev.known
    if known is None or known.logo_url is None:
        return Escalate("Wikidata names no logo file for this website")
    saved, problem = await save_logo_file(known.logo_url, ev, ctx)
    if saved is None:
        return Escalate(f"the logo file Wikidata names {problem}")
    return Resolved(
        value=Logo(url=known.logo_url, image_file=saved),
        confidence=0.8,
        source=f"{known.source}: its logo file",
        evidence=(known.logo_url,),
    )


logo_by_decider = _logo_by(second=False)
logo_by_second_opinion = _logo_by(second=True)


async def resolve_logo(ev: Evidence, ctx: RunContext) -> LogoResult:
    """The business's logo: the page's most logo-like image, and when the rules aren't sure of
    it, the numbered candidate a model picks on the screenshot, then a second model's pick."""
    steps = [logo_from_the_page, logo_by_decider, logo_by_second_opinion, logo_from_known_file]
    return await run_cascade(steps, ev, ctx)
