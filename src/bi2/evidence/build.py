"""Puts a page's evidence together, from what loading the page captured."""

from bi2.core.models import Evidence, PageInfo, PageKind, PageSnapshot
from bi2.evidence.countries import find_postcodes, guess_countries, page_languages
from bi2.evidence.document import parse_html
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
    postcodes = find_postcodes("\n".join((text.header, text.main, text.footer)))
    countries = guess_countries(
        base,
        address_country=structured.address.country if structured.address else None,
        languages=page_languages(doc),
        postcodes=postcodes,
    )
    return Evidence(
        page=PageInfo(
            url=snapshot.url,
            final_url=snapshot.final_url,
            kind=PageKind.UNKNOWN if refused else PageKind.OWN_WEBSITE,
        ),
        meta=extract_meta(doc, base),
        structured=structured,
        text=shorten(text),
        countries=countries,
    )
