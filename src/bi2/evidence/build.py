"""Puts a page's evidence together, from what loading the page captured."""

from collections.abc import Iterable

from bi2.core.models import Evidence, PageInfo, PageKind, PageSnapshot
from bi2.evidence.contacts import extract_contacts, phone_countries
from bi2.evidence.countries import (
    find_postcodes,
    find_region_countries,
    guess_countries,
    page_languages,
)
from bi2.evidence.document import parse_html
from bi2.evidence.links import extract_contact_pages, extract_social_links
from bi2.evidence.logos import extract_logo_candidates
from bi2.evidence.meta import extract_meta
from bi2.evidence.structured import extract_structured_data
from bi2.evidence.text import extract_text_regions, shorten


def build_evidence(snapshot: PageSnapshot) -> Evidence:
    """Everything the field resolvers need from a loaded page, gathered without model calls."""
    doc = parse_html(snapshot.html)
    base = snapshot.final_url
    refused = snapshot.status_code is not None and snapshot.status_code >= 400
    structured = extract_structured_data(doc, base)
    text = extract_text_regions(snapshot, doc)
    all_text = "\n".join((text.header, text.main, text.footer))
    postcodes = find_postcodes(all_text)
    regions = find_region_countries(all_text)
    languages = page_languages(doc)

    def likely_countries(phones: Iterable[str] = ()) -> tuple[str, ...]:
        return guess_countries(
            base,
            address_country=structured.address.country if structured.address else None,
            languages=languages,
            postcodes=postcodes,
            regions=regions,
            phone_countries=phone_countries(phones),
        )

    # Phone numbers are read as the likeliest country's, then count as a clue themselves.
    hint = likely_countries()
    contacts = extract_contacts(
        doc,
        text,
        structured_phone=structured.telephone,
        region=hint[0] if hint else None,
        postcodes=(postcode for postcode, _ in postcodes),
    )
    countries = likely_countries(contacts.phones)
    meta = extract_meta(doc, base)
    return Evidence(
        page=PageInfo(
            url=snapshot.url,
            final_url=snapshot.final_url,
            kind=PageKind.UNKNOWN if refused else PageKind.OWN_WEBSITE,
        ),
        meta=meta,
        structured=structured,
        logo_candidates=extract_logo_candidates(
            snapshot.images, doc, base, meta=meta, structured=structured
        ),
        text=shorten(text),
        contacts=contacts,
        social_links=extract_social_links(doc, base, listed=structured.same_as),
        countries=countries,
        contact_pages=extract_contact_pages(doc, base),
    )
