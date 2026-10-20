"""What the steps that ask a model share, for the answers the rules aren't sure of.

Every such step:
- passes to the next when the run has no model, saying so;
- asks with only the evidence the question needs, never the whole page;
- lets a model's failure fail the step, so the field keeps the rules' best answer;
- reports what its call cost, for the field's audit trail.

How sure an answer is comes from the model's probability for it, and from whether it agrees
with the rules: two methods that agree are surer than either alone.
"""

import re
from typing import Final

from bi2.core.asking import Ask, Decision
from bi2.core.context import RunContext
from bi2.core.models import Evidence
from bi2.core.text import clean_space
from bi2.core.urls import registrable_domain

NO_MODEL: Final = "no model was asked: set JEV_API_KEY or GEMINI_API_KEY to use one"
NO_SECOND: Final = "no second model to ask: it takes both a Jev and a Gemini key"
NONE: Final = "none"  # the option for "none of these", in every choice that has one

# How sure an answer is, from the model's probability for it and whether it agrees with the
# rules' best answer. Tuned on the gold set; see docs/architecture.md.
_AGREES_SURE, _AGREES_LIKELY = 0.6, 0.4
_DIFFERS_SURE, _DIFFERS_LIKELY = 0.85, 0.6


def confidence(probability: float, *, agrees: bool) -> float:
    """How sure an answer a model gave is."""
    if agrees:
        if probability >= _AGREES_SURE:
            return 0.92
        return 0.8 if probability >= _AGREES_LIKELY else 0.6
    if probability >= _DIFFERS_SURE:
        return 0.86
    return 0.72 if probability >= _DIFFERS_LIKELY else 0.5


def sure_of_one(probability: float) -> float | None:
    """How sure a yes to "is this the one?" about a single value is, or None when the model
    doubts it. With one value, agreeing with the rules says nothing, so only the model's
    probability counts."""
    if probability >= 0.85:
        return 0.9
    return 0.75 if probability >= 0.6 else None


async def ask_decider(ask: Ask, ctx: RunContext, *, second: bool = False) -> Decision | str:
    """The run's Decider's answers, or why none was asked. With `second`, the second model's,
    for a second opinion. A model that fails raises ModelUnavailable."""
    decider = ctx.second if second else ctx.decider
    if decider is None:
        return NO_SECOND if second else NO_MODEL
    return await decider.decide(ask)


def who(decision: Decision) -> str:
    """The model that answered, for an answer's source."""
    return decision.model


def site_lines(ev: Evidence) -> list[str]:
    """The lines that say whose website it is, for the top of a question's state."""
    page = ev.page
    lines = [f"Website: {registrable_domain(page.final_url or page.url)}"]
    if page.platform:
        lines.append(f"This is the business's profile on {page.platform}, not its own website.")
    if ev.meta.title:
        lines.append(f"Page title: {ev.meta.title}")
    if ev.meta.site_name:
        lines.append(f"Site name: {ev.meta.site_name}")
    if ev.meta.description:
        lines.append(f"Description: {ev.meta.description[:300]}")
    return lines


def around(
    text: str, pattern: str | re.Pattern[str], *, width: int = 70, most: int = 2
) -> list[str]:
    """The text around the first few places a pattern appears, to show a value in context."""
    found = []
    for match in re.finditer(pattern, text, flags=re.IGNORECASE):
        start, end = max(0, match.start() - width), min(len(text), match.end() + width)
        found.append(clean_space(text[start:end]))
        if len(found) == most:
            break
    return found


def digits_pattern(phone: str) -> str:
    """A pattern for a phone number as pages write it: its last 7 digits, with anything but
    digits allowed between them, like "555-0123" or "555 01 23"."""
    digits = re.sub(r"\D", "", phone)[-7:]
    return r"\D{0,3}".join(digits)
