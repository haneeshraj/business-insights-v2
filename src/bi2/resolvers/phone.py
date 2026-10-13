"""The business's main phone number, from where its pages show it.

A number the page shows in more than one place, or gives in its structured data or as a link
to call, is the business's. One that appears only in the middle of the page could be anyone's,
so it needs review. When the homepage shows no number, the site's contact page is read too; a
contact page that lists several numbers, such as one per store, leaves the main one unclear,
so it needs review.
"""

from typing import Final

from bi2.core.context import RunContext
from bi2.core.models import Contacts, Evidence, PhoneNumber, PhoneResult
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
# A contact page that lists more numbers than this, such as one per store, leaves the main one
# unclear.
_MANY: Final = 2
_SURE_AMONG_MANY: Final = 0.7


def _confidence(places: tuple[str, ...]) -> float:
    if len(places) > 1:
        return _SURE_IN_SEVERAL_PLACES
    return max((_SURE_BY_PLACE.get(place, 0.5) for place in places), default=0.5)


def _best(contacts: Contacts) -> tuple[PhoneNumber, tuple[str, ...]]:
    """The number shown most clearly as the business's, and where. Ties go to page order."""
    places = contacts.phone_places
    best = max(contacts.phones, key=lambda phone: _confidence(places.get(phone, ())))
    return best, places.get(best, ())


async def phone_from_the_page(ev: Evidence, ctx: RunContext) -> Resolved[PhoneNumber] | Escalate:
    """The number the page shows most clearly as the business's own."""
    if not ev.contacts.phones:
        return Escalate("no phone number on the page")
    best, found_in = _best(ev.contacts)
    return Resolved(
        value=best,
        confidence=_confidence(found_in),
        source=" + ".join(found_in) or "the page",
        evidence=tuple(f"{place}: {best}" for place in found_in),
    )


async def phone_from_the_contact_page(
    ev: Evidence, ctx: RunContext
) -> Resolved[PhoneNumber] | Escalate:
    """The number the site's contact page shows most clearly as the business's own."""
    page = ev.contact_page
    if page is None:
        return Escalate("no contact page was read")
    if not page.contacts.phones:
        return Escalate("no phone number on the contact page either")
    best, found_in = _best(page.contacts)
    sure = _confidence(found_in)
    if len(page.contacts.phones) > _MANY:
        sure = min(sure, _SURE_AMONG_MANY)
    return Resolved(
        value=best,
        confidence=sure,
        source="contact page: " + (" + ".join(found_in) or "the page"),
        evidence=(f"contact page: {page.url}", *(f"{place}: {best}" for place in found_in)),
    )


async def resolve_phone(ev: Evidence, ctx: RunContext) -> PhoneResult:
    """The business's main phone number: from its homepage, then its contact page. Search
    joins as a later step."""
    return await run_cascade([phone_from_the_page, phone_from_the_contact_page], ev, ctx)
