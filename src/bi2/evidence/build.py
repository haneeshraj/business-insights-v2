"""Puts a page's evidence together, from what loading the page captured."""

from collections.abc import Iterable

from bi2.core.models import (
    ContactPage,
    Contacts,
    CountryCode,
    Evidence,
    PageInfo,
    PageKind,
    PageMeta,
    PageSnapshot,
    StructuredData,
    TextRegions,
)
from bi2.core.text import names_match
from bi2.evidence.contacts import extract_contacts, phone_countries
from bi2.evidence.countries import (
    find_postcodes,
    find_region_countries,
    guess_countries,
    page_languages,
)
from bi2.evidence.document import Document, links, parse_html
from bi2.evidence.links import extract_contact_pages, extract_social_links
from bi2.evidence.logos import extract_logo_candidates
from bi2.evidence.meta import extract_meta
from bi2.evidence.platforms import (
    Profile,
    page_profile,
    platform_of,
    platforms,
    profile_name,
    unwrap_link,
)
from bi2.evidence.structured import extract_structured_data
from bi2.evidence.text import extract_text_regions, shorten


def _without_platform_branding(
    platform: str, meta: PageMeta, structured: StructuredData
) -> tuple[PageMeta, StructuredData]:
    """On a platform's page, its name as the site name and its structured data about itself
    describe the platform, not the business, so they're left out."""
    name = platforms()[platform].name
    if names_match(meta.site_name, name):
        meta = meta.model_copy(update={"site_name": ""})
    if structured.name and names_match(structured.name, name):
        structured = StructuredData()
    return meta, structured


def _own_website(doc: Document, base_url: str, platform: str) -> str | None:
    """The business's own site, when its profile links to it through the platform."""
    for url, _ in links(doc, base_url):
        target = unwrap_link(url, platform)
        if target and platform_of(target) is None:
            return target
    return None


def _page_info(
    snapshot: PageSnapshot, doc: Document, meta: PageMeta, profile: Profile | None
) -> PageInfo:
    """What kind of page it is: the business's own site, or its page on a platform."""
    refused = snapshot.status_code is not None and snapshot.status_code >= 400
    if profile is not None and not refused:
        return PageInfo(
            url=snapshot.url,
            final_url=snapshot.final_url,
            kind=PageKind.PLATFORM_PROFILE,
            platform=profile.platform,
            profile_name=profile_name(meta.og_title or meta.title, profile.platform),
            own_website=_own_website(doc, snapshot.final_url, profile.platform),
        )
    # A refused page, or a platform's page that isn't a profile, says nothing about the business.
    on_platform = platform_of(snapshot.final_url) or platform_of(snapshot.url)
    kind = PageKind.UNKNOWN if refused or on_platform else PageKind.OWN_WEBSITE
    return PageInfo(url=snapshot.url, final_url=snapshot.final_url, kind=kind)


def _contacts_and_countries(
    doc: Document, base_url: str, structured: StructuredData, text: TextRegions
) -> tuple[Contacts, tuple[CountryCode, ...]]:
    """The contact details and the likely countries, which depend on each other: phone numbers
    are read as the likeliest country's, then count as a clue to the country themselves."""
    all_text = "\n".join((text.header, text.main, text.footer))
    postcodes = find_postcodes(all_text)
    regions = find_region_countries(all_text)
    languages = page_languages(doc)

    def likely_countries(phones: Iterable[str] = ()) -> tuple[CountryCode, ...]:
        return guess_countries(
            base_url,
            address_country=structured.address.country if structured.address else None,
            languages=languages,
            postcodes=postcodes,
            regions=regions,
            phone_countries=phone_countries(phones),
        )

    hint = likely_countries()
    contacts = extract_contacts(
        doc,
        text,
        structured_phone=structured.telephone,
        structured_email=structured.email,
        region=hint[0] if hint else None,
        postcodes=(postcode for postcode, _ in postcodes),
    )
    return contacts, likely_countries(contacts.phones)


def build_contact_page(snapshot: PageSnapshot) -> ContactPage:
    """The contact details on a site's contact page, read like the homepage's."""
    doc = parse_html(snapshot.html)
    structured = extract_structured_data(doc, snapshot.final_url)
    text = extract_text_regions(snapshot, doc)
    contacts, _ = _contacts_and_countries(doc, snapshot.final_url, structured, text)
    return ContactPage(url=snapshot.final_url, contacts=contacts)


def build_evidence(snapshot: PageSnapshot) -> Evidence:
    """Everything the field resolvers need from a loaded page, gathered without model calls."""
    doc = parse_html(snapshot.html)
    base = snapshot.final_url
    meta = extract_meta(doc, base)
    structured = extract_structured_data(doc, base)
    profile = page_profile(snapshot.url, snapshot.final_url)
    if profile is not None:
        meta, structured = _without_platform_branding(profile.platform, meta, structured)
    page = _page_info(snapshot, doc, meta, profile)
    text = extract_text_regions(snapshot, doc)
    contacts, countries = _contacts_and_countries(doc, base, structured, text)
    if profile is not None:  # the copyright line on a platform's page is the platform's
        contacts = contacts.model_copy(update={"copyright_line": None})
    # On a social platform, the profile itself is one of the business's social links, and the
    # page's other links are the platform's own.
    listed = list(structured.same_as)
    if profile is not None and platforms()[profile.platform].social:
        listed.insert(0, snapshot.url)
    logos = extract_logo_candidates(
        snapshot.images,
        doc,
        base,
        meta=meta,
        structured=structured,
        profile=profile,
        profile_name=page.profile_name,
    )
    return Evidence(
        page=page,
        meta=meta,
        structured=structured,
        logo_candidates=logos,
        text=shorten(text),
        contacts=contacts,
        social_links=extract_social_links(
            doc, base, listed=listed, from_page_links=profile is None
        ),
        countries=countries,
        contact_pages=extract_contact_pages(doc, base) if profile is None else (),
    )
