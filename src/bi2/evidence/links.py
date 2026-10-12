"""Links that matter as evidence: the business's social media profiles, and its own pages
that likely hold its address and phone number, such as Contact and About."""

from collections.abc import Iterable
from typing import Final
from urllib.parse import urldefrag, urlsplit

from bi2.core.models import SocialProfile
from bi2.core.text import fold
from bi2.core.urls import absolute_url, same_site, social_key
from bi2.evidence.document import Document, attribute
from bi2.evidence.platforms import find_profile, platforms

_KEEP_PROFILES: Final = 20
_KEEP_PAGES: Final = 3

# Words in a link's address or text that point to a page with contact details.
_CONTACT_WORDS: Final = (
    "contact", "about", "our-story", "location", "find-us", "visit", "store-locator", "stores",
    "hours", "impressum", "kontakt", "nous-joindre", "a-propos",
)  # fmt: skip


def _links(doc: Document, base_url: str) -> list[tuple[str, str]]:
    """Every web link on the page, as (URL, link text), in page order."""
    links = []
    for anchor in doc.css("a[href]"):
        url = absolute_url(base_url, attribute(anchor, "href"))
        if url:
            links.append((url, anchor.text()))
    return links


def extract_social_links(
    doc: Document, base_url: str, *, listed: Iterable[str] = ()
) -> tuple[SocialProfile, ...]:
    """The social media profiles the page points to: those listed in its structured data
    first, then those it links to, in page order. Share buttons and posts aren't profiles."""
    found: dict[str, SocialProfile] = {}
    for url in [*listed, *(url for url, _ in _links(doc, base_url))]:
        profile = find_profile(url)
        if profile is not None and platforms()[profile.platform].social:
            found.setdefault(social_key(url), SocialProfile(platform=profile.platform, url=url))
    return tuple(found.values())[:_KEEP_PROFILES]


def extract_contact_pages(doc: Document, base_url: str) -> tuple[str, ...]:
    """The site's own pages most likely to hold its address and phone number, best first."""
    here = urldefrag(base_url).url.rstrip("/")
    points: dict[str, int] = {}
    for url, text in _links(doc, base_url):
        url = urldefrag(url).url
        if url.rstrip("/") == here or not same_site(url, base_url):
            continue
        path, words = urlsplit(url).path.casefold(), fold(text)
        score = sum(2 for word in _CONTACT_WORDS if word in path)
        score += sum(1 for word in _CONTACT_WORDS if word.replace("-", " ") in words)
        if score:
            points[url] = max(points.get(url, 0), score)
    ranked = sorted(points, key=lambda url: -points[url])  # ties keep page order
    return tuple(ranked[:_KEEP_PAGES])
