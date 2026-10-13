"""The business's email address, from where its pages show it.

An address on the business's own domain, in an email link, is the business's. One on another
domain, like a Gmail address, is common for small businesses but could be anyone's, so it
counts for less. An address for one purpose, like privacy or jobs, goes after a general one,
and one nobody reads, like noreply, isn't used at all. When the homepage shows no address, the
site's contact page is read too.
"""

import re
from typing import Final

from bi2.core.context import RunContext
from bi2.core.models import Contacts, EmailAddress, EmailResult, Evidence
from bi2.core.urls import registrable_domain
from bi2.resolvers.cascade import Escalate, Resolved, run_cascade

# How sure an address is, by the most telling place it was found in.
_SURE_BY_PLACE: Final = {"email link": 0.9, "footer": 0.85, "header": 0.85, "main text": 0.7}
_SURE_IN_SEVERAL_PLACES: Final = 0.95
_LESS_SURE_ON_ANOTHER_DOMAIN: Final = 0.15
_LESS_SURE_FOR_ONE_PURPOSE: Final = 0.2

_NOBODY_READS: Final = re.compile(r"^(?:no-?reply|do-?not-?reply|bounce|mailer-daemon)\b")
_ONE_PURPOSE: Final = re.compile(
    r"^(?:privacy|dpo|gdpr|data|legal|careers?|jobs?|hr|recruit\w*|press|media|pr|investors?|ir"
    r"|accessibility|abuse|postmaster|webmaster|security|unsubscribe)[@._-]"
)


def _confidence(email: str, places: tuple[str, ...], site: str) -> float:
    sure = (
        _SURE_IN_SEVERAL_PLACES
        if len(places) > 1
        else max((_SURE_BY_PLACE.get(place, 0.5) for place in places), default=0.5)
    )
    if registrable_domain(email.rsplit("@", 1)[1]) != site:
        sure -= _LESS_SURE_ON_ANOTHER_DOMAIN
    if _ONE_PURPOSE.match(email):
        sure -= _LESS_SURE_FOR_ONE_PURPOSE
    return round(sure, 2)


def _best(contacts: Contacts, site: str) -> tuple[EmailAddress, tuple[str, ...], float] | None:
    """The address shown most clearly as the business's general one, where it was, and how
    sure that is. Ties go to page order."""
    usable = [email for email in contacts.emails if not _NOBODY_READS.match(email)]
    if not usable:
        return None
    places = contacts.email_places
    scored = [(email, _confidence(email, places.get(email, ()), site)) for email in usable]
    email, sure = max(scored, key=lambda pair: pair[1])
    return email, places.get(email, ()), sure


def _answer(
    found: tuple[EmailAddress, tuple[str, ...], float], where: str
) -> Resolved[EmailAddress]:
    email, places, sure = found
    return Resolved(
        value=email,
        confidence=sure,
        source=where + (" + ".join(places) or "the page"),
        evidence=tuple(f"{place}: {email}" for place in places),
    )


async def email_from_the_page(ev: Evidence, ctx: RunContext) -> Resolved[EmailAddress] | Escalate:
    """The address the page shows most clearly as the business's own."""
    found = _best(ev.contacts, registrable_domain(ev.page.final_url or ev.page.url))
    if found is None:
        return Escalate("no email address on the page")
    return _answer(found, "")


async def email_from_the_contact_page(
    ev: Evidence, ctx: RunContext
) -> Resolved[EmailAddress] | Escalate:
    """The address the site's contact page shows most clearly as the business's own."""
    page = ev.contact_page
    if page is None:
        return Escalate("no contact page was read")
    found = _best(page.contacts, registrable_domain(ev.page.final_url or ev.page.url))
    if found is None:
        return Escalate("no email address on the contact page either")
    return _answer(found, "contact page: ")


async def resolve_email(ev: Evidence, ctx: RunContext) -> EmailResult:
    """The business's email address: from its homepage, then its contact page."""
    return await run_cascade([email_from_the_page, email_from_the_contact_page], ev, ctx)
