"""The business's main phone number, from where its page shows it.

A number the page shows in more than one place, or gives in its structured data or as a link
to call, is the business's. One that appears only in the middle of the page could be anyone's,
so it needs review.
"""

from typing import Final

from bi2.core.context import RunContext
from bi2.core.models import Evidence, PhoneNumber, PhoneResult
from bi2.resolvers.cascade import Escalate, Resolved, run_cascade

# How sure a number is, by the most telling place it was found in.
_SURE_BY_PLACE: Final = {
    "structured data": 0.9,
    "call link": 0.9,
    "footer": 0.85,
    "header": 0.85,
    "main text": 0.6,
}
_SURE_IN_SEVERAL_PLACES: Final = 0.95


def _confidence(places: tuple[str, ...]) -> float:
    if len(places) > 1:
        return _SURE_IN_SEVERAL_PLACES
    return max((_SURE_BY_PLACE.get(place, 0.5) for place in places), default=0.5)


async def phone_from_the_page(ev: Evidence, ctx: RunContext) -> Resolved[PhoneNumber] | Escalate:
    """The number the page shows most clearly as the business's own."""
    phones, places = ev.contacts.phones, ev.contacts.phone_places
    if not phones:
        return Escalate("no phone number on the page")
    best = max(phones, key=lambda phone: _confidence(places.get(phone, ())))  # ties: page order
    found_in = places.get(best, ())
    return Resolved(
        value=best,
        confidence=_confidence(found_in),
        source=" + ".join(found_in) or "the page",
        evidence=tuple(f"{place}: {best}" for place in found_in),
    )


async def resolve_phone(ev: Evidence, ctx: RunContext) -> PhoneResult:
    """The business's main phone number. Contact pages and search join as later steps."""
    return await run_cascade("phone", [phone_from_the_page], ev, ctx)
