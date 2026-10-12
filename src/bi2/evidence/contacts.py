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
from bi2.evidence.document import Document, attribute

_KEEP: Final = 10  # the most of each kind of detail kept

_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,24}")
# Things shaped like email addresses that aren't: retina image names, and the addresses of
# services and placeholders that site builders leave in pages.
_NOT_EMAIL_ENDINGS: Final = (".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".avif")
_NOT_EMAIL_DOMAINS: Final = ("example.com", "domain.com", "email.com", "sentry.io", "wixpress.com")

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


def find_phones(
    doc: Document, text: TextRegions, *, structured: str | None, region: str | None
) -> list[str]:
    """Valid phone numbers on the page in E.164 format, most telling first: the structured
    data's, then call links, then numbers in the footer, the header and the main text.
    Numbers written without a country code are read as the region's (the US by default)."""
    region = region or "US"
    numbers = [_parse(structured, region)] if structured else []
    for link in doc.css('a[href^="tel:" i]'):
        numbers.append(_parse(unquote(attribute(link, "href")[4:]), region))
    for part in (text.footer, text.header, text.main):
        numbers += [match.number for match in phonenumbers.PhoneNumberMatcher(part, region)]
    found = (phonenumbers.format_number(n, PhoneNumberFormat.E164) for n in numbers if n)
    return list(dict.fromkeys(found))[:_KEEP]


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


def find_emails(doc: Document, text: TextRegions) -> list[str]:
    """Email addresses from the page's email links and text, lowercased."""
    found = [
        unquote(attribute(a, "href")[7:]).split("?")[0] for a in doc.css('a[href^="mailto:" i]')
    ]
    for part in (text.footer, text.header, text.main):
        found += _EMAIL.findall(part)
    emails = []
    for email in (address.strip().lower() for address in found):
        if (
            _EMAIL.fullmatch(email)
            and not email.endswith(_NOT_EMAIL_ENDINGS)
            and not email.rsplit("@", 1)[1].endswith(_NOT_EMAIL_DOMAINS)
        ):
            emails.append(email)
    return list(dict.fromkeys(emails))[:_KEEP]


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
    region: str | None,
    postcodes: Iterable[str],
) -> Contacts:
    """Every contact detail on the page."""
    return Contacts(
        phones=tuple(find_phones(doc, text, structured=structured_phone, region=region)),
        emails=tuple(find_emails(doc, text)),
        postcodes=tuple(list(dict.fromkeys(postcodes))[:_KEEP]),
        copyright_line=find_copyright_line(text),
    )
