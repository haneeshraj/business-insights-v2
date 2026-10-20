"""Answers from what Wikidata knows about the business, for a page that couldn't be read, like
one behind a bot check.

Wikidata knows big brands by the official websites they list there, so a match is the business
itself. Its name is sure when it matches the site's domain, like "No Frills" for nofrills.ca,
and needs review when it doesn't, like "Roots Canada" for roots.com. A logo is its file on
Wikimedia Commons, checked like any logo. Accounts, phone numbers and emails there can be out
of date, so they need review. A step with nothing to give fails, so a field Wikidata knows
nothing about stays an error: the page couldn't be read.
"""

from typing import Any, Final

from pydantic import TypeAdapter, ValidationError

from bi2.core.context import RunContext
from bi2.core.errors import FetchError
from bi2.core.models import (
    CompanyName,
    EmailAddress,
    Evidence,
    KnownBusiness,
    Logo,
    PhoneNumber,
    SocialLinks,
)
from bi2.core.text import fold
from bi2.core.urls import domain_name
from bi2.evidence.contacts import normalize_phone
from bi2.resolvers.cascade import Resolved, Step
from bi2.resolvers.logo import save_logo_file

_SURE: Final = 0.85
_LESS_SURE: Final = 0.7  # a name that doesn't match the domain, or details that can be stale


def _known(ev: Evidence, what: str) -> KnownBusiness:
    if ev.known is None:
        raise FetchError("Wikidata doesn't know a business with this website")
    if not getattr(ev.known, what):
        raise FetchError(f"Wikidata has no {what.replace('_', ' ')} for {ev.known.source}")
    return ev.known


async def name_from_wikidata(ev: Evidence, ctx: RunContext) -> Resolved[CompanyName]:
    """The name Wikidata gives the business."""
    known = _known(ev, "name")
    letters = "".join(char for char in fold(known.name) if char.isalnum())
    matches = letters == "".join(char for char in domain_name(ev.page.url) if char.isalnum())
    return Resolved(
        value=known.name,
        confidence=_SURE if matches else _LESS_SURE,
        source=f"{known.source}: its name",
        evidence=(f"https://www.wikidata.org/wiki/{known.item}",),
    )


async def logo_from_wikidata(ev: Evidence, ctx: RunContext) -> Resolved[Logo]:
    """The logo file Wikidata names for the business."""
    known = _known(ev, "logo_url")
    assert known.logo_url is not None
    saved, problem = await save_logo_file(known.logo_url, ev, ctx)
    if saved is None:
        raise FetchError(f"the logo Wikidata names {problem}")
    return Resolved(
        value=Logo(url=known.logo_url, image_file=saved),
        confidence=_SURE,
        source=f"{known.source}: its logo",
        evidence=(known.logo_url,),
    )


async def social_from_wikidata(ev: Evidence, ctx: RunContext) -> Resolved[SocialLinks]:
    """The accounts Wikidata lists for the business."""
    known = _known(ev, "social_links")
    return Resolved(
        value=known.social_links,
        confidence=_LESS_SURE,
        source=f"{known.source}: its accounts",
        evidence=tuple(profile.url for profile in known.social_links),
    )


async def phone_from_wikidata(ev: Evidence, ctx: RunContext) -> Resolved[PhoneNumber]:
    """The phone number Wikidata lists for the business."""
    known = _known(ev, "phone")
    phone = normalize_phone(known.phone, "US")
    if phone is None:
        raise FetchError(f"the phone number Wikidata lists isn't one: {known.phone}")
    return Resolved(value=phone, confidence=_LESS_SURE, source=f"{known.source}: its phone number")


async def email_from_wikidata(ev: Evidence, ctx: RunContext) -> Resolved[EmailAddress]:
    """The email address Wikidata lists for the business."""
    known = _known(ev, "email")
    try:
        email = TypeAdapter(EmailAddress).validate_python(known.email.lower())
    except ValidationError as exc:
        raise FetchError(f"the email Wikidata lists isn't one: {known.email}") from exc
    return Resolved(value=email, confidence=_LESS_SURE, source=f"{known.source}: its email")


# The step for each field that Wikidata can answer.
KNOWN_STEPS: Final[dict[str, Step[Any]]] = {
    "company_name": name_from_wikidata,
    "logo": logo_from_wikidata,
    "phone": phone_from_wikidata,
    "email": email_from_wikidata,
    "social_links": social_from_wikidata,
}
