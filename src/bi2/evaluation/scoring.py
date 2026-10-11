"""Compares one site's result with its gold-set entry, field by field."""

import re
from enum import StrEnum
from typing import Final, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict

from bi2.core.models import (
    FIELD_NAMES,
    Address,
    AddressResult,
    LogoResult,
    MccResult,
    NameResult,
    PageKind,
    SiteResult,
    Status,
)
from bi2.core.text import fold, names_match
from bi2.evaluation.gold import ExpectedAddress, GoldSite

# Everything scored for a site: its page kind, then each output field.
SCORED_FIELDS: Final = ("page_kind", *FIELD_NAMES)

# The gold-set attribute that holds each output field's expected answers.
_GOLD_ATTRIBUTE: Final = {
    "company_name": "company_names",
    "logo": "logo_urls",
    "mcc": "mcc_codes",
    "address": "address",
}

_HOUSE_NUMBER = re.compile(r"^\s*(\d+[A-Za-z]?)\b")
_NOT_ALPHANUMERIC = re.compile(r"[^0-9A-Z]")
_IMAGE_EXTENSION = re.compile(r"\.(png|jpe?g|gif|svg|webp|avif|ico)", re.IGNORECASE)
# Size tags that image CDNs add to file names: logo_400x.png, logo_300x300.png, logo-300x100.png
_SIZE_TAG = re.compile(r"(?:[_-](?:\d+x\d*|\{width\}x))+$", re.IGNORECASE)


class Verdict(StrEnum):
    """How one answer compares with the gold set."""

    CORRECT = "correct"
    WRONG = "wrong"  # answered, with the wrong value
    MISSED = "missed"  # an answer was expected, but none was given
    UNEXPECTED = "unexpected"  # the gold set says there is none, but an answer was given
    NOT_SCORED = "not_scored"  # the gold set doesn't check this field for this site


class FieldScore(BaseModel):
    """The verdict on one field of one site."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    field: str
    verdict: Verdict
    needs_review: bool = False
    got: str = ""
    expected: str = ""


def _verdict(*, absent_expected: bool, answered: bool, correct: bool) -> Verdict:
    if absent_expected:
        return Verdict.UNEXPECTED if answered else Verdict.CORRECT
    if not answered:
        return Verdict.MISSED
    return Verdict.CORRECT if correct else Verdict.WRONG


def score_page_kind(result: SiteResult, gold: GoldSite) -> FieldScore:
    """Whether the page was recognized as the business's own site or the right platform."""
    page = result.page
    correct = page.kind is gold.page_kind and fold(page.platform or "") == fold(gold.platform or "")
    return FieldScore(
        field="page_kind",
        verdict=_verdict(
            absent_expected=False, answered=page.kind is not PageKind.UNKNOWN, correct=correct
        ),
        got=page.kind.value + (f" ({page.platform})" if page.platform else ""),
        expected=gold.page_kind.value + (f" ({gold.platform})" if gold.platform else ""),
    )


def score_name(result: NameResult, expected: tuple[str, ...] | None) -> FieldScore:
    """Correct when the name matches any accepted name after normalization."""
    if expected is None:
        return FieldScore(field="company_name", verdict=Verdict.NOT_SCORED)
    value = result.value
    correct = value is not None and any(names_match(value, name) for name in expected)
    return FieldScore(
        field="company_name",
        verdict=_verdict(absent_expected=False, answered=value is not None, correct=correct),
        needs_review=result.status is Status.NEEDS_REVIEW,
        got=value or "",
        expected=" | ".join(expected),
    )


def image_key(url: str) -> str:
    """A key under which the same image matches however its URL is written.

    Ignores the scheme, "www.", query strings, CDN size tags in the file name, and anything a
    CDN appends after the file name (such as Wix's `/v1/fill/...`).
    """
    parts = urlsplit(url)
    path = parts.path
    extension = _IMAGE_EXTENSION.search(path)
    if extension:
        stem = _SIZE_TAG.sub("", path[: extension.start()])
        path = f"{stem}.{extension.group(1).lower()}"
    return parts.netloc.casefold().removeprefix("www.") + path.casefold()


def score_logo(
    result: LogoResult, expected: tuple[str, ...] | Literal["none"] | None
) -> FieldScore:
    """Correct when the logo URL matches an accepted URL, ignoring scheme, "www." and query."""
    if expected is None:
        return FieldScore(field="logo", verdict=Verdict.NOT_SCORED)
    logo = result.value
    got = (logo.url or logo.image_file or "") if logo else ""
    shown: str
    if isinstance(expected, str):  # "none"
        verdict = _verdict(absent_expected=True, answered=logo is not None, correct=False)
        shown = expected
    else:
        accepted = {image_key(url) for url in expected}
        correct = logo is not None and logo.url is not None and image_key(logo.url) in accepted
        verdict = _verdict(absent_expected=False, answered=logo is not None, correct=correct)
        shown = " | ".join(expected)
    return FieldScore(
        field="logo",
        verdict=verdict,
        needs_review=result.status is Status.NEEDS_REVIEW,
        got=got,
        expected=shown,
    )


def score_mcc(result: MccResult, expected: tuple[str, ...] | None) -> FieldScore:
    """Correct when the code is one of the accepted codes."""
    if expected is None:
        return FieldScore(field="mcc", verdict=Verdict.NOT_SCORED)
    value = result.value
    correct = value is not None and value.code in expected
    return FieldScore(
        field="mcc",
        verdict=_verdict(absent_expected=False, answered=value is not None, correct=correct),
        needs_review=result.status is Status.NEEDS_REVIEW,
        got=f"{value.code} {value.description}" if value else "",
        expected=" | ".join(expected),
    )


def address_matches(got: Address, want: ExpectedAddress) -> bool:
    """Whether an answer matches on postal code (or city, when there is none) and house number."""
    text = " ".join(part for part in (got.text, got.street, got.city, got.postal_code) if part)
    if want.postal_code:
        squashed = _NOT_ALPHANUMERIC.sub("", text.upper())
        if _NOT_ALPHANUMERIC.sub("", want.postal_code.upper()) not in squashed:
            return False
    elif want.city and fold(want.city) not in fold(text):
        return False
    number = _HOUSE_NUMBER.match(want.street or "")
    if number is None:
        return True
    return re.search(rf"\b{re.escape(number.group(1))}\b", text, re.IGNORECASE) is not None


def _describe(address: ExpectedAddress) -> str:
    return ", ".join(part for part in (address.street, address.city, address.postal_code) if part)


def score_address(
    result: AddressResult, expected: ExpectedAddress | Literal["none"] | None
) -> FieldScore:
    """Correct when the address matches on postal code and house number."""
    if expected is None:
        return FieldScore(field="address", verdict=Verdict.NOT_SCORED)
    value = result.value
    shown: str
    if isinstance(expected, str):  # "none"
        verdict = _verdict(absent_expected=True, answered=value is not None, correct=False)
        shown = expected
    else:
        correct = value is not None and address_matches(value, expected)
        verdict = _verdict(absent_expected=False, answered=value is not None, correct=correct)
        shown = _describe(expected)
    return FieldScore(
        field="address",
        verdict=verdict,
        needs_review=result.status is Status.NEEDS_REVIEW,
        got=value.text if value else "",
        expected=shown,
    )


def score_site(gold: GoldSite, result: SiteResult | None) -> tuple[FieldScore, ...]:
    """Score every field of one site, in SCORED_FIELDS order. A site with no result misses
    everything the gold set checks for it."""
    if result is None:
        return tuple(
            FieldScore(
                field=name,
                verdict=Verdict.MISSED
                if name == "page_kind" or getattr(gold, _GOLD_ATTRIBUTE[name]) is not None
                else Verdict.NOT_SCORED,
            )
            for name in SCORED_FIELDS
        )
    return (
        score_page_kind(result, gold),
        score_name(result.company_name, gold.company_names),
        score_logo(result.logo, gold.logo_urls),
        score_mcc(result.mcc, gold.mcc_codes),
        score_address(result.address, gold.address),
    )
