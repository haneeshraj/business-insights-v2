"""Contact details on the page: phone numbers, email addresses, postcodes and the copyright
line, which often names the company that owns the business."""

import re
from collections.abc import Iterable
from typing import Final
from urllib.parse import unquote

import phonenumbers
from phonenumbers import NumberParseException, PhoneNumberFormat, PhoneNumberType

from bi2.core.models import Contacts, TextRegions
from bi2.core.text import clean_space
from bi2.core.urls import public_suffix
from bi2.evidence.document import Document, attribute, visible_text

_KEEP: Final = 10  # the most of each kind of detail kept

_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,24}")
_MAILTO = re.compile(r"^\s*mailto:", re.I)
# Addresses spelled out so spam robots can't read them, like "info(at)example.fi" or
# "info [at] example [dot] com", and the full-width at sign Japanese pages often use.
_SPELLED_AT = re.compile(
    r"\s*[(\[{]\s*(?:at|ät|@|arroba)\s*[)\]}]\s*|\N{FULLWIDTH COMMERCIAL AT}", re.I
)
_SPELLED_DOT = re.compile(r"\s*[(\[{]\s*(?:dot|punkt|punto|ponto|point)\s*[)\]}]\s*", re.I)
# Things shaped like email addresses that aren't: retina image names, and the addresses of
# services and placeholders that site builders leave in pages.
_NOT_EMAIL_ENDINGS: Final = (".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".avif")
_NOT_EMAIL_DOMAINS: Final = (
    "example.com", "domain.com", "email.com", "company.com", "yourdomain.com", "sample.com",
    "test.com", "sentry.io", "wixpress.com",
)  # fmt: skip

_COPYRIGHT_SIGN = re.compile(r"\N{COPYRIGHT SIGN}")
_COPYRIGHT_WORD = re.compile(r"(?:\bcopyright|\(c\))\s*\N{COPYRIGHT SIGN}?\s*(?:19|20)\d\d", re.I)

# Numbers that don't say where a business is, so they don't count as a country clue.
_NOT_LOCAL: Final = frozenset(
    {
        PhoneNumberType.TOLL_FREE,
        PhoneNumberType.PREMIUM_RATE,
        PhoneNumberType.SHARED_COST,
        PhoneNumberType.UAN,
        PhoneNumberType.VOIP,
        PhoneNumberType.PERSONAL_NUMBER,
    }
)


def _parse(raw: str, region: str) -> phonenumbers.PhoneNumber | None:
    try:
        number = phonenumbers.parse(raw, region)
    except NumberParseException:
        return None
    return number if phonenumbers.is_valid_number(number) else None


def normalize_phone(raw: str, region: str = "CA") -> str | None:
    """A phone number as written by a person, in E.164 format, or None if it isn't a valid
    number. `region` is the country to assume when the number has no country code."""
    number = _parse(raw, region)
    return phonenumbers.format_number(number, PhoneNumberFormat.E164) if number else None


def find_phones(
    doc: Document, text: TextRegions, *, structured: str | None, region: str | None
) -> dict[str, list[str]]:
    """Valid phone numbers on the page in E.164 format, each with the places it was found,
    most telling first: the structured data, call links, then the footer, the header and the
    main text. Numbers written without a country code are read as the region's (the US by
    default)."""
    region = region or "US"
    found: list[tuple[phonenumbers.PhoneNumber | None, str]] = []
    if structured:
        found.append((_parse(structured, region), "structured data"))
    for link in doc.css('a[href^="tel:" i]'):
        found.append((_parse(unquote(attribute(link, "href")[4:]), region), "call link"))
    for place, part in (("footer", text.footer), ("header", text.header), ("main text", text.main)):
        found += [(match.number, place) for match in phonenumbers.PhoneNumberMatcher(part, region)]
    places: dict[str, list[str]] = {}
    for number, place in found:
        if number is not None:
            seen = places.setdefault(phonenumbers.format_number(number, PhoneNumberFormat.E164), [])
            if place not in seen:
                seen.append(place)
    return dict(list(places.items())[:_KEEP])


def phone_countries(phones: Iterable[str]) -> list[str]:
    """The countries these E.164 numbers belong to, leaving out toll-free numbers and others
    that aren't tied to a place."""
    countries = []
    for phone in phones:
        number = phonenumbers.parse(phone)
        region = phonenumbers.region_code_for_number(number)
        if region and phonenumbers.number_type(number) not in _NOT_LOCAL:
            countries.append(region)
    return countries


def _unspelled(text: str) -> str:
    """The text with spelled-out addresses written the usual way: "info(at)example.fi" becomes
    "info@example.fi"."""
    return _SPELLED_DOT.sub(".", _SPELLED_AT.sub("@", text))


def _leading_address(raw: str) -> str:
    """The address an email link or a structured-data value starts with, without "mailto:" or
    anything after the address, like "?subject=" or a stray tag."""
    match = _EMAIL.match(_MAILTO.sub("", unquote(raw)).strip())
    return match.group(0) if match else ""


def _is_email(email: str) -> bool:
    domain = email.rsplit("@", 1)[-1]
    return bool(
        _EMAIL.fullmatch(email)
        and not email.endswith(_NOT_EMAIL_ENDINGS)
        # A whole domain or a subdomain of it: "thecoffeecompany.com" isn't "company.com".
        and not any(domain == name or domain.endswith(f".{name}") for name in _NOT_EMAIL_DOMAINS)
        and public_suffix(f"https://{domain}")  # a real ending, unlike "your@mail.address"
    )


def find_emails(
    doc: Document, text: TextRegions, *, structured: str | None = None
) -> dict[str, list[str]]:
    """Email addresses on the page, lowercased, each with the places it was found, most telling
    first: the structured data, email links, then the footer, the header and the main text.
    Addresses spelled out for spam robots, like "info(at)example.fi", count too.

    An address in none of those places but in the page's code as text, like in a closed
    accordion or a dialog, is found in "hidden text"."""
    found = [(_leading_address(structured), "structured data")] if structured else []
    found += [
        (_leading_address(attribute(a, "href")), "email link")
        for a in doc.css('a[href^="mailto:" i]')
    ]
    for place, part in (("footer", text.footer), ("header", text.header), ("main text", text.main)):
        found += [(address, place) for address in _EMAIL.findall(_unspelled(part))]
    if doc.body is not None:
        hidden = _EMAIL.findall(_unspelled(visible_text(doc.body)))
        found += [(address, "hidden text") for address in hidden]
    places: dict[str, list[str]] = {}
    for address, place in found:
        email = address.strip().lower()
        if not _is_email(email) or (place == "hidden text" and places.get(email)):
            continue
        seen = places.setdefault(email, [])
        if place not in seen:
            seen.append(place)
    return dict(list(places.items())[:_KEEP])


def find_copyright_line(text: TextRegions) -> str | None:
    """The copyright line, such as "\N{COPYRIGHT SIGN} 2026 Example Cafe Ltd.", from the copyright
    sign on. The footer is looked at first."""
    for pattern in (_COPYRIGHT_SIGN, _COPYRIGHT_WORD):
        for part in (text.footer, text.main, text.header):
            for line in part.splitlines():
                match = pattern.search(line)
                if match:
                    return clean_space(line[match.start() :])[:200]
    return None


# Parts of a copyright line that aren't its holder: the sign, years, dashes, and everything from
# "All rights reserved", "Powered by" or a "|" on.
_NOT_HOLDER = re.compile(
    r"\N{COPYRIGHT SIGN}|\(c\)|\bcopyright\b|\b(?:19|20)\d\d\b|[-\N{EN DASH}]"
    r"|(?:all rights reserved|powered by|designed by|website by|site by|\|).*$",
    re.I,
)


def copyright_holder(line: str) -> str:
    """Who a copyright line names: "Example Cafe Ltd" from "\N{COPYRIGHT SIGN} 2026 Example Cafe
    Ltd. All rights reserved."."""
    return clean_space(_NOT_HOLDER.sub(" ", line)).strip(" .,;:")


def extract_contacts(
    doc: Document,
    text: TextRegions,
    *,
    structured_phone: str | None,
    structured_email: str | None = None,
    region: str | None,
    postcodes: Iterable[str],
) -> Contacts:
    """Every contact detail on the page."""
    phones = find_phones(doc, text, structured=structured_phone, region=region)
    emails = find_emails(doc, text, structured=structured_email)
    return Contacts(
        phones=tuple(phones),
        phone_places={phone: tuple(places) for phone, places in phones.items()},
        emails=tuple(emails),
        email_places={email: tuple(places) for email, places in emails.items()},
        postcodes=tuple(list(dict.fromkeys(postcodes))[:_KEEP]),
        copyright_line=find_copyright_line(text),
    )
