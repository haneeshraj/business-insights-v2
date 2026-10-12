"""How many of the gold set's answers the evidence already holds, before any model runs.

That's the most the free sources can get right. A field whose answer isn't anywhere in the
evidence needs search or a model, so this shows where the cost will go.
"""

import re
from collections.abc import Iterable
from typing import Final

from pydantic import BaseModel, ConfigDict

from bi2.core.models import Address, Evidence
from bi2.core.text import clean_space, fold, names_match
from bi2.core.urls import image_key, social_key
from bi2.evaluation.gold import ExpectedAddress, GoldSite
from bi2.evaluation.scoring import address_matches
from bi2.evidence.contacts import copyright_holder

# Each check, in report order.
CHECKS: Final = (
    "page_kind",
    "company_name",
    "logo (any candidate)",
    "logo (top candidate)",
    "address (structured data)",
    "address (page text)",
    "country (top guess)",
    "phone",
    "social_links",
)

# Where page titles split into parts, as in "Menu | Example Cafe - Toronto".
_TITLE_PARTS = re.compile(r"\s+[|\-:\N{EN DASH}\N{EM DASH}\N{MIDDLE DOT}\N{BULLET}]\s+")


class FieldCoverage(BaseModel):
    """Whether one of a site's gold answers is somewhere in its evidence, and where."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    check: str
    found: bool
    where: str = ""  # the part of the evidence that holds the answer


def names_in(ev: Evidence) -> list[tuple[str, str]]:
    """Every name in the evidence that could be the business's, with where it was found."""
    found = [
        ("profile name", ev.page.profile_name or ""),
        ("structured data", ev.structured.name or ""),
        ("structured data legal name", ev.structured.legal_name or ""),
        ("site name", ev.meta.site_name),
        ("og:title", ev.meta.og_title),
        ("title", ev.meta.title),
    ]
    for where, title in (("title", ev.meta.title), ("og:title", ev.meta.og_title)):
        found += [(f"part of the {where}", part) for part in _TITLE_PARTS.split(title)]
    found += [("logo alt text", candidate.alt) for candidate in ev.logo_candidates]
    if ev.contacts.copyright_line:
        found.append(("copyright line", copyright_holder(ev.contacts.copyright_line)))
    return [(where, clean_space(name)) for where, name in found if name.strip()]


def _first(checks: Iterable[tuple[str, bool]]) -> tuple[bool, str]:
    for where, ok in checks:
        if ok:
            return True, where
    return False, ""


def _name(names: tuple[str, ...], ev: Evidence) -> FieldCoverage:
    found, where = _first(
        (where, any(names_match(candidate, name) for name in names))
        for where, candidate in names_in(ev)
    )
    return FieldCoverage(check="company_name", found=found, where=where)


def _logo(urls: tuple[str, ...], ev: Evidence) -> list[FieldCoverage]:
    accepted = {image_key(url) for url in urls}
    numbers = [c.number for c in ev.logo_candidates if c.url and image_key(c.url) in accepted]
    top = bool(numbers) and numbers[0] == min(c.number for c in ev.logo_candidates)
    return [
        FieldCoverage(
            check="logo (any candidate)",
            found=bool(numbers),
            where=f"candidate {numbers[0]}" if numbers else "",
        ),
        FieldCoverage(check="logo (top candidate)", found=top, where="candidate 1" if top else ""),
    ]


def _address_in_text(text: str, want: ExpectedAddress) -> bool:
    # Addresses take up to three lines; looking at a few lines at a time keeps a house number
    # elsewhere on the page from counting.
    lines = [line for line in text.splitlines() if line.strip()]
    windows = (" ".join(lines[start : start + 3]) for start in range(len(lines)))
    return any(address_matches(Address(text=window), want) for window in windows)


def _address(want: ExpectedAddress, ev: Evidence) -> list[FieldCoverage]:
    structured = ev.structured.address is not None and address_matches(ev.structured.address, want)
    text = "\n".join((ev.text.header, ev.text.main, ev.text.footer))
    in_text = _address_in_text(text, want)
    return [
        FieldCoverage(check="address (structured data)", found=structured),
        FieldCoverage(check="address (page text)", found=in_text),
    ]


def _phone(phones: tuple[str, ...], ev: Evidence) -> FieldCoverage:
    found = [phone for phone in ev.contacts.phones if phone in phones]
    return FieldCoverage(check="phone", found=bool(found), where=found[0] if found else "")


def _social(links: tuple[str, ...], ev: Evidence) -> FieldCoverage:
    found = [*ev.structured.same_as, *(profile.url for profile in ev.social_links)]
    keys = {social_key(url) for url in found}
    missing = [url for url in links if social_key(url) not in keys]
    return FieldCoverage(
        check="social_links",
        found=not missing,
        where=f"missing {', '.join(missing)}" if missing else "",
    )


def evidence_coverage(gold: GoldSite, ev: Evidence) -> tuple[FieldCoverage, ...]:
    """Check each answer the gold set lists for a site against the site's evidence."""
    page_kind = ev.page.kind is gold.page_kind and fold(ev.page.platform or "") == fold(
        gold.platform or ""
    )
    checks = [FieldCoverage(check="page_kind", found=page_kind, where=ev.page.kind.value)]
    if gold.company_names:
        checks.append(_name(gold.company_names, ev))
    if isinstance(gold.logo_urls, tuple):
        checks += _logo(gold.logo_urls, ev)
    if isinstance(gold.address, ExpectedAddress):
        checks += _address(gold.address, ev)
        if gold.address.country:
            top = ev.countries[0] if ev.countries else ""
            checks.append(
                FieldCoverage(
                    check="country (top guess)", found=top == gold.address.country, where=top
                )
            )
    if isinstance(gold.phones, tuple):
        checks.append(_phone(gold.phones, ev))
    if isinstance(gold.social_links, tuple):
        checks.append(_social(gold.social_links, ev))
    return tuple(checks)


def summarize(sites: Iterable[tuple[FieldCoverage, ...]]) -> dict[str, tuple[int, int]]:
    """For each check: on how many sites the answer was found, and how many it applied to."""
    totals = {check: [0, 0] for check in CHECKS}
    for site in sites:
        for coverage in site:
            totals[coverage.check][0] += coverage.found
            totals[coverage.check][1] += 1
    return {check: (found, checked) for check, (found, checked) in totals.items() if checked}
