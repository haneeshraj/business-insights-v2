"""The business's main phone number, from where its pages show it.

A number the page shows in more than one place, or gives in its structured data or as a link
to call, is the business's. One that appears only in the middle of the page could be anyone's,
so it needs review. When the homepage shows no number, the site's contact page is read too; a
contact page that lists several numbers, such as one per store, leaves the main one unclear,
so it needs review.
"""

from typing import Final

from bi2.core.asking import Ask, Choice, YesNo
from bi2.core.context import RunContext
from bi2.core.models import Contacts, Evidence, PhoneNumber, PhoneResult
from bi2.resolvers.asking import (
    NONE,
    around,
    ask_decider,
    confidence,
    digits_pattern,
    site_lines,
    sure_of_one,
)
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


_JUDGE_VERSION: Final = "1"
_MAIN: Final = (
    "the business's own main phone number, the one its customers call: not a fax, a "
    "partner's or a supplier's number, a number for one purpose like the press or jobs, or a "
    "number for another business"
)
_MOST_NUMBERS: Final = 8


def _numbers(ev: Evidence) -> list[tuple[PhoneNumber, tuple[str, ...]]]:
    """Every number the homepage and the contact page show, and where."""
    found: dict[PhoneNumber, tuple[str, ...]] = {}
    for contacts, prefix in (
        (ev.contacts, ""),
        (ev.contact_page.contacts if ev.contact_page else None, "contact page "),
    ):
        if contacts is None:
            continue
        for phone in contacts.phones:
            places = tuple(prefix + place for place in contacts.phone_places.get(phone, ()))
            found[phone] = found.get(phone, ()) + (places or (prefix.strip() or "the page",))
    return list(found.items())[:_MOST_NUMBERS]


async def phone_by_decider(ev: Evidence, ctx: RunContext) -> Resolved[PhoneNumber] | Escalate:
    """The number a model judges the business's main one, from where the pages show each, when
    the rules aren't sure."""
    numbers = _numbers(ev)
    if not numbers:
        return Escalate("no number for a model to judge")
    text = "\n".join((ev.text.header, ev.text.main, ev.text.footer))
    lines = site_lines(ev)
    for phone, places in numbers:
        shown = around(text, digits_pattern(phone))
        lines.append(
            f"{phone}: found in {', '.join(places)}"
            + "".join(f'\n  shown as: "{s}"' for s in shown)
        )
    if len(numbers) == 1:
        phone = numbers[0][0]
        question: Choice | YesNo = YesNo(instructions=f"Is {phone} {_MAIN}?")
    else:
        options = {phone: f"{phone}, found in {', '.join(places)}" for phone, places in numbers}
        options[NONE] = "None of these is the business's main number"
        question = Choice(instructions=f"Which of these is {_MAIN}?", options=options)
    ask = Ask(
        task="phone_pick",
        version=_JUDGE_VERSION,
        state="\n".join(lines),
        questions={"phone": question},
    )
    decision = await ask_decider(ask, ctx)
    if isinstance(decision, str):
        return Escalate(decision)
    if isinstance(question, YesNo):
        probability = decision.agreed("phone").probability
        sure = sure_of_one(probability)
        if sure is None:
            return Escalate(
                f"{decision.model} doubts it's the main number ({probability:.2f})",
                cost=decision.cost,
            )
        chosen = numbers[0][0]
    else:
        contacts = (
            ev.contacts
            if ev.contacts.phones
            else ev.contact_page.contacts
            if ev.contact_page
            else None
        )
        rules = _best(contacts)[0] if contacts is not None and contacts.phones else None
        picked = decision.picked("phone")
        probability = picked.probability(picked.choice)
        if picked.choice == NONE:
            return Escalate(
                f"{decision.model} says none is the main number ({probability:.2f})",
                cost=decision.cost,
            )
        chosen = picked.choice
        sure = confidence(probability, agrees=chosen == rules)
    return Resolved(
        value=chosen,
        confidence=sure,
        source=f"{decision.model}: judged the main number ({probability:.2f})",
        evidence=tuple(f"{place}: {chosen}" for place in dict(numbers).get(chosen, ())),
        cost=decision.cost,
    )


async def resolve_phone(ev: Evidence, ctx: RunContext) -> PhoneResult:
    """The business's main phone number: from its homepage, then its contact page, then a
    model's judgment of the numbers they show."""
    steps = [phone_from_the_page, phone_from_the_contact_page, phone_by_decider]
    return await run_cascade(steps, ev, ctx)
