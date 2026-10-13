"""Links that matter as evidence: the business's social media profiles, and its own pages
that likely hold its address and phone number, such as Contact and About."""

import re
from collections.abc import Iterable
from typing import Final
from urllib.parse import urldefrag, urlsplit

from bi2.core.models import SocialProfile
from bi2.core.text import fold
from bi2.core.urls import same_site, social_key
from bi2.evidence.document import Document, links
from bi2.evidence.platforms import find_profile, platforms

_KEEP_PROFILES: Final = 20
_KEEP_PAGES: Final = 3

# Words in a link's address or text that point to a page with contact details, and how much
# each counts. A page named for contact details counts most, in the languages of the sites v2
# reads. Then legal notices, which in many countries must show a phone number and an email
# address. Then pages that often hold an address.
_CONTACT_WORDS: Final = {
    "contact": 3, "kontakt": 3, "contacto": 3, "contatti": 3, "contato": 3, "contactez": 3,
    "nous-joindre": 3, "yhteystiedot": 3, "iletisim": 3,
    # Enquiries are often for one thing, like "Media enquiries" or "Business inquiries".
    "inquir": 2, "enquir": 2,
    "impressum": 2, "imprint": 2, "mentions-legales": 2, "aviso-legal": 2, "note-legali": 2,
    "legal-notice": 2,
    "about": 1, "our-story": 1, "a-propos": 1, "location": 1, "find-us": 1, "visit": 1,
    "store-locator": 1, "stores": 1, "hours": 1,
}  # fmt: skip

# Words in a page's address that say it's for one purpose, not for reaching the business, or
# that it's an article or a product: the press, careers, franchising, a blog, a product page.
_ONE_PURPOSE_PAGE: Final = re.compile(
    r"(?:^|[/_.-])(?:press|media|news|blog|careers?|jobs?|franchis\w*|invest\w*|sponsor\w*"
    r"|donat\w*|donors?|wholesale|privacy|cookies?|terms|explore|learn|recipes?|products?)"
    r"(?=$|[/_.-])"
)
# Link text longer than this is a teaser for an article or an offer, not a menu label.
_LONGEST_LINK_LABEL: Final = 6


def extract_social_links(
    doc: Document, base_url: str, *, listed: Iterable[str] = (), from_page_links: bool = True
) -> tuple[SocialProfile, ...]:
    """The social media profiles the page points to: those listed first, such as the ones in
    its structured data, then those it links to, in page order. Share buttons and posts aren't
    profiles. On a platform's page, the links are the platform's own, so they're left out."""
    page_links = [url for url, _ in links(doc, base_url)] if from_page_links else []
    found: dict[str, SocialProfile] = {}
    for url in [*listed, *page_links]:
        profile = find_profile(url)
        if profile is not None and platforms()[profile.platform].social:
            found.setdefault(social_key(url), SocialProfile(platform=profile.platform, url=url))
    return tuple(found.values())[:_KEEP_PROFILES]


def _best_weight(found_in: str, *, weak_too: bool = True) -> int:
    """The weight of the most telling contact word in a link's address or text."""
    return max(
        (
            weight
            for word, weight in _CONTACT_WORDS.items()
            if (weak_too or weight > 1) and word in found_in
        ),
        default=0,
    )


def extract_contact_pages(doc: Document, base_url: str) -> tuple[str, ...]:
    """The site's own pages most likely to hold its address and phone number, best first.

    A link's text counts as much as its address, so "Contact us" leading to /help counts as
    much as /contact. A page for one purpose, like the press or careers, is never taken, even
    when its address says "enquiries". In long link text, like a blog post's teaser, weak words
    such as "about" don't count."""
    here = urldefrag(base_url).url.rstrip("/")
    points: dict[str, int] = {}
    for url, text in links(doc, base_url):
        url = urldefrag(url).url
        if url.rstrip("/") == here or not same_site(url, base_url):
            continue
        path, words = urlsplit(url).path.casefold(), fold(text)
        if _ONE_PURPOSE_PAGE.search(path):
            continue
        teaser = len(words.split()) > _LONGEST_LINK_LABEL
        score = 2 * _best_weight(path) + 2 * _best_weight(
            words.replace(" ", "-"), weak_too=not teaser
        )
        if score:
            points[url] = max(points.get(url, 0), score)
    ranked = sorted(points, key=lambda url: -points[url])  # ties keep page order
    return tuple(ranked[:_KEEP_PAGES])
