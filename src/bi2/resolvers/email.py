"""The business's email address, from where its pages show it.

The business's general address is the one wanted, like info@ or hello@, or their equivalents in
the languages of the sites v2 reads:

- An address on the business's own domain comes first. That's the site's domain, or another
  one named for the same business, like rainhardbrewery.com for rainhardbrewing.com. An
  address on another domain, like a Gmail address, is common for small businesses but could be
  anyone's, so it counts for less.
- A general address comes before any other, like a person's or a store's, and one made only
  of general words, like customer.care@, before one naming a product or a place too, like
  helpdesk.campus@.
- The answer needs review when it isn't plainly the general one: an address made of general
  words and others, or one of several on the page that are neither general nor for one
  purpose, like one per store.
- An address for one purpose, like privacy, press or jobs, is never the answer, nor is one
  nobody reads, like noreply.
- An address only in hidden text, like a closed accordion, counts only when it's a general one
  on the business's own domain.

When the homepage shows no address that could be the answer, the site's contact page is read
too.
"""

import re
from typing import Final, NamedTuple

from bi2.core.context import RunContext
from bi2.core.models import Contacts, EmailAddress, EmailResult, Evidence, PageKind
from bi2.core.urls import domain_name, registrable_domain
from bi2.resolvers.cascade import Escalate, Resolved, run_cascade

# How sure an address is, by the most telling place it was found in.
_SURE_BY_PLACE: Final = {
    "structured data": 0.9,
    "email link": 0.9,
    "footer": 0.85,
    "header": 0.85,
    "main text": 0.7,
    "hidden text": 0.6,
}
_SURE_IN_SEVERAL_PLACES: Final = 0.95
_LESS_SURE_ON_ANOTHER_DOMAIN: Final = 0.15
# The most an address can be when it isn't plainly the general one.
_SURE_WHEN_UNCLEAR: Final = 0.7

_NOBODY_READS: Final = re.compile(r"^(?:no-?reply|do-?not-?reply|bounces?|mailer-daemon)\b")

# What an address's name, the part before the @, says it's for. Short words must be a whole
# part of the name, split at dots, dashes, underscores and plus signs, so "press" doesn't match
# "espresso". Stems can be anywhere in it, like "service" in "customerservice".
_PART_BREAK: Final = re.compile(r"[._+-]")
_ONE_PURPOSE_PARTS: Final = frozenset(
    {
        "ads", "ap", "cv", "data", "dmca", "dpo", "dsb", "finance", "gdpr", "hr", "ir", "job",
        "jobs", "legal", "media", "news", "pers", "pr", "press", "presse", "rfp", "rgpd", "rh",
        "rrhh", "spam", "stampa",
    }
)  # fmt: skip
_ONE_PURPOSE_STEMS: Final = re.compile(
    "|".join(
        (
            # privacy, the law and security
            "privac", "datenschutz", "dataprotect", "complian", "copyright", "licens", "ethic",
            "whistle", "security", "abuse", "fraud", "phishing", "postmaster", "webmaster",
            "hostmaster", "unsubscribe", "accessib",
            # jobs
            "career", "carriere", "karriere", "karriar", "recruit", "recrut", "reclut", "rekryt",
            "bewerbung", "emploi", "empleo", "emprego", "talent",
            # the press, marketing, partners and events
            "imprensa", "prensa", "communicat", "comunicac", "kommunikat", "newsletter",
            "marketing", "advertis", "publicit", "publicid", "werbung", "sponsor", "commandit",
            "patrocin", "partner", "partenar", "affiliat", "influenc", "ambassad", "collab",
            "kooperation", "community", "event", "evenement", "veranstalt",
            # investors, suppliers and the accounts
            "invest", "sharehold", "supplier", "fournisseur", "proveedor", "fornecedor",
            "lieferant", "vendor", "procurement", "tender", "proposal", "propost", "propuesta",
            "payable", "invoic", "factur", "fatura", "rechnung", "billing", "accounting",
            "comptab", "contabil", "buchhaltung",
            # business other than the customers'
            "b2b", "wholesale", "franchis", "franquic", "busdevelop", "bizdev", "businessdev",
            "corporatesale", "corporategift", "leasing", "realestate", "donation", "donacion",
            "volunteer", "benevol", "alumni",
        )
    )
)  # fmt: skip
_GENERAL_PARTS: Final = frozenset(
    {
        "ask", "bilgi", "bonjour", "chat", "ciao", "cs", "email", "eshop", "general", "geral",
        "hallo", "hej", "hey", "hi", "hola", "mail", "merhaba", "moi", "oi", "ola", "post",
        "posta", "sac", "salut", "shop", "staff", "team", "webshop",
    }
)  # fmt: skip
_GENERAL_STEMS: Final = re.compile(
    "|".join(
        (
            "information", "info", "hello", "welcome", "contact", "contato", "contatti",
            "kontakt", "iletisim", "yhteys", "boxoffice", "office", "oficina", "escritorio", "bureau",
            # Whole words before their stems, so a word's ending isn't left over: "enquiries"
            # is all general, where "enquir" would leave "ies".
            "ufficio", "kontor", "enquiries", "inquiries", "enquir", "inquir", "servicio", "servic",
            "servizi", "palvelu", "support",
            "apoio", "help", "frontdesk", "desk", "care", "customer", "client", "guest", "member", "kund",
            "klant", "asiakas", "atencion", "atendimento", "reception",
        )
    )
)  # fmt: skip
# Short names that a business's other domains can't be told by: "cafe" in "cafemilano".
_SHORTEST_BRAND: Final = 5


class _Candidate(NamedTuple):
    email: EmailAddress
    places: tuple[str, ...]
    own: bool  # on the business's own domain
    general: bool  # a general address, like info@
    plain: bool  # made only of general words, like customer.care@
    sure: float


def _name(email: str) -> str:
    return email.rsplit("@", 1)[0]


def _says(email: str, parts: frozenset[str], stems: re.Pattern[str]) -> bool:
    name = _name(email)
    return bool(stems.search(name)) or any(part in parts for part in _PART_BREAK.split(name))


def _plainly_general(email: str) -> bool:
    """Whether the address's name is only general words, like "info" or "customer.care", rather
    than one with other words too, like a product's or a place's: "w4bsupport", "help.campus".
    Joining letters, like "us" in "contactus", don't count as words."""
    for part in _PART_BREAK.split(_name(email)):
        if part not in _GENERAL_PARTS and any(len(rest) > 2 for rest in _GENERAL_STEMS.split(part)):
            return False
    return True


def _same_business(a: str, b: str) -> bool:
    """Whether two domain names, without their endings, are the same business's: the same, one
    in the other, or sharing most of their start, like "rainhardbrewing" and "rainhardbrewery"."""
    if a == b:
        return True
    shorter, longer = sorted((a, b), key=len)
    if len(shorter) < _SHORTEST_BRAND:
        return False
    shared = next(
        (i for i, (x, y) in enumerate(zip(shorter, longer, strict=False)) if x != y), len(shorter)
    )
    return shorter in longer or (shared >= _SHORTEST_BRAND and shared > len(shorter) / 2)


def _sure(places: tuple[str, ...], own: bool) -> float:
    sure = (
        _SURE_IN_SEVERAL_PLACES
        if len(places) > 1
        else max((_SURE_BY_PLACE.get(place, 0.5) for place in places), default=0.5)
    )
    return round(sure if own else sure - _LESS_SURE_ON_ANOTHER_DOMAIN, 2)


def _domains(ev: Evidence) -> tuple[tuple[str, ...], str | None]:
    """The names of the business's own domains, from the address given and the one it led to,
    and on a platform profile, the platform's domain, whose addresses are never the business's."""
    page = ev.page
    here = page.final_url or page.url
    if page.kind is PageKind.PLATFORM_PROFILE:
        own = (domain_name(page.own_website),) if page.own_website else ()
        return own, registrable_domain(here)
    return tuple(dict.fromkeys(domain_name(url) for url in (page.url, here))), None


def _candidates(contacts: Contacts, ev: Evidence) -> list[_Candidate]:
    """The addresses that could be the business's general one, in page order."""
    owns, platform = _domains(ev)
    found = []
    for email in contacts.emails:
        places = contacts.email_places.get(email, ())
        domain = email.rsplit("@", 1)[1]
        if (
            registrable_domain(domain) == platform
            or _NOBODY_READS.match(email)
            or _says(email, _ONE_PURPOSE_PARTS, _ONE_PURPOSE_STEMS)
        ):
            continue
        own = any(_same_business(domain_name(domain), name) for name in owns)
        general = _says(email, _GENERAL_PARTS, _GENERAL_STEMS)
        if places == ("hidden text",) and not (own and general):
            continue
        plain = general and _plainly_general(email)
        found.append(_Candidate(email, places, own, general, plain, _sure(places, own)))
    return found


def _best(candidates: list[_Candidate]) -> _Candidate | None:
    """The address shown most clearly as the business's general one. Ties go to page order."""
    if not candidates:
        return None
    best = max(candidates, key=lambda found: (found.own, found.general, found.plain, found.sure))
    alike = [
        found
        for found in candidates
        if found is not best and (found.own, found.general) == (best.own, best.general)
    ]
    if (best.general and not best.plain) or (alike and not best.general):
        return best._replace(sure=min(best.sure, _SURE_WHEN_UNCLEAR))
    return best


def shows_an_email(ev: Evidence) -> bool:
    """Whether the homepage shows an address that could be the business's general one."""
    return bool(_candidates(ev.contacts, ev))


def _answer(
    contacts: Contacts, ev: Evidence, where: str, also: str
) -> Resolved[EmailAddress] | Escalate:
    found = _best(_candidates(contacts, ev))
    if found is None:
        if not contacts.emails:
            return Escalate(f"no email address on {where}{also}")
        shown = ", ".join(contacts.emails[:2])
        return Escalate(f"no address on {where} could be the business's general one{also}: {shown}")
    prefix = "contact page: " if where == "the contact page" else ""
    return Resolved(
        value=found.email,
        confidence=found.sure,
        source=prefix + (" + ".join(found.places) or "the page"),
        evidence=tuple(f"{place}: {found.email}" for place in found.places),
    )


async def email_from_the_page(ev: Evidence, ctx: RunContext) -> Resolved[EmailAddress] | Escalate:
    """The address the page shows most clearly as the business's general one."""
    return _answer(ev.contacts, ev, "the page", "")


async def email_from_the_contact_page(
    ev: Evidence, ctx: RunContext
) -> Resolved[EmailAddress] | Escalate:
    """The address the site's contact page shows most clearly as the business's general one."""
    if ev.contact_page is None:
        return Escalate("no contact page was read")
    return _answer(ev.contact_page.contacts, ev, "the contact page", " either")


async def resolve_email(ev: Evidence, ctx: RunContext) -> EmailResult:
    """The business's email address: from its homepage, then its contact page."""
    return await run_cascade([email_from_the_page, email_from_the_contact_page], ev, ctx)
